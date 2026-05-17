"""Tests for app/account_settings/services.py (Phase 2 schema).

Contract source: task spec (Phase 2 Account Settings Service).

Requires DATABASE_URL to run (skipped otherwise). Each test creates a fresh
random user_id so tests are independent without requiring transaction rollback.

Schema under test (Phase 2):
    public.categories:        id UUID PK, user_id UUID, name TEXT, created_at TIMESTAMPTZ
                              UNIQUE(user_id, name)
    public.category_keywords: id UUID PK, category_id UUID FK→categories(id) ON DELETE CASCADE,
                              keyword TEXT, created_at TIMESTAMPTZ
                              UNIQUE(category_id, keyword)

NOTE: The old custom_categories table is gone after migration 0002.
"""

import os
import uuid

import pytest

from app import create_app

DATABASE_URL = os.environ.get("DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="DATABASE_URL must be set to run account settings service tests",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def app_ctx():
    """Module-scoped Flask app context so service calls have current_app available."""
    app = create_app()
    app.config["TESTING"] = True
    with app.app_context():
        yield


def _uid() -> str:
    """Return a UUID string guaranteed to have no category data."""
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# TestGetCategoryMap
# ---------------------------------------------------------------------------

class TestGetCategoryMap:
    def test_returns_empty_dict_for_unknown_user(self, app_ctx):
        """A user_id with no saved categories must return {} (not None, not a
        seeded map). get_category_map does NOT auto-seed — that is seed_defaults'
        job."""
        from app.account_settings.services import get_category_map

        result = get_category_map(_uid())

        assert isinstance(result, dict)
        assert result == {}, (
            "get_category_map must return {} for a user with no categories, "
            "not auto-seed a default map"
        )

    def test_returns_saved_map_for_known_user(self, app_ctx):
        """After save_category_map is called, get_category_map must return the
        same names and keywords that were saved."""
        from app.account_settings.services import get_category_map, save_category_map

        user_id = _uid()
        category_map = {"Food": ["PIZZA HUT", "SUSHI PLACE"], "Transport": ["UBER"]}

        save_category_map(user_id, category_map)
        result = get_category_map(user_id)

        assert isinstance(result, dict)
        assert set(result.keys()) == {"Food", "Transport"}
        assert sorted(result["Food"]) == sorted(["PIZZA HUT", "SUSHI PLACE"])
        assert result["Transport"] == ["UBER"]

    def test_different_user_ids_are_isolated(self, app_ctx):
        """User A's categories must be invisible to user B and vice versa.
        This is the user-isolation invariant."""
        from app.account_settings.services import get_category_map, save_category_map

        user_a = _uid()
        user_b = _uid()

        save_category_map(user_a, {"Food": ["BURGER KING"]})
        save_category_map(user_b, {"Travel": ["AIRBNB"]})

        result_a = get_category_map(user_a)
        result_b = get_category_map(user_b)

        assert "Travel" not in result_a, "User A must not see User B's categories"
        assert "Food" not in result_b, "User B must not see User A's categories"


# ---------------------------------------------------------------------------
# TestSaveCategoryMap
# ---------------------------------------------------------------------------

class TestSaveCategoryMap:
    def test_first_call_persists_map(self, app_ctx):
        """First call for a new user_id must write the map so get_category_map
        returns it."""
        from app.account_settings.services import get_category_map, save_category_map

        user_id = _uid()
        category_map = {"Utilities": ["HYDRO ONE", "ROGERS"]}

        save_category_map(user_id, category_map)

        assert get_category_map(user_id) == category_map

    def test_second_call_replaces_existing_map_entirely(self, app_ctx):
        """A second call must replace all previous categories and keywords —
        no accumulation of old entries (single write path contract)."""
        from app.account_settings.services import get_category_map, save_category_map

        user_id = _uid()
        first_map = {"Food": ["TIM HORTONS"]}
        second_map = {"Transport": ["GO TRANSIT", "UBER"]}

        save_category_map(user_id, first_map)
        save_category_map(user_id, second_map)

        result = get_category_map(user_id)

        assert "Food" not in result, "Old category must be gone after full replace"
        assert "Transport" in result

    def test_normalizes_category_name_whitespace(self, app_ctx):
        """Category names are stripped and internal whitespace collapsed before
        insert. '  Fast  Food  ' must be stored as 'Fast Food'."""
        from app.account_settings.services import get_category_map, save_category_map

        user_id = _uid()
        save_category_map(user_id, {"  Fast  Food  ": ["MCDONALDS"]})

        result = get_category_map(user_id)

        assert "Fast Food" in result, "Normalized name must appear in result"
        assert "  Fast  Food  " not in result, "Unnormalized name must not appear"

    def test_normalizes_keywords_to_uppercase(self, app_ctx):
        """Keywords are stripped and uppercased before insert. 'loblaws' must
        be stored as 'LOBLAWS'."""
        from app.account_settings.services import get_category_map, save_category_map

        user_id = _uid()
        save_category_map(user_id, {"Groceries": [" loblaws "]})

        result = get_category_map(user_id)

        assert "LOBLAWS" in result["Groceries"], (
            "Keyword must be uppercased and stripped after normalization"
        )
        assert " loblaws " not in result["Groceries"]

    def test_deduplicates_keywords_within_category(self, app_ctx):
        """Duplicate keywords in the same category after normalization must be
        stored only once."""
        from app.account_settings.services import get_category_map, save_category_map

        user_id = _uid()
        save_category_map(user_id, {"Food": ["PIZZA", "pizza", " PIZZA "]})

        result = get_category_map(user_id)

        assert result["Food"].count("PIZZA") == 1, "Duplicate keyword must be deduplicated"

    def test_calling_twice_with_same_map_is_idempotent(self, app_ctx):
        """Calling save_category_map twice with the same map must leave the
        database in the same state as calling it once."""
        from app.account_settings.services import get_category_map, save_category_map

        user_id = _uid()
        category_map = {"Food": ["SUSHI"], "Transport": ["UBER"]}

        save_category_map(user_id, category_map)
        save_category_map(user_id, category_map)

        result = get_category_map(user_id)

        assert set(result.keys()) == {"Food", "Transport"}
        assert result["Food"] == ["SUSHI"]

    def test_raises_value_error_if_input_is_not_a_dict(self, app_ctx):
        """Passing a non-dict as category_map must raise ValueError."""
        from app.account_settings.services import save_category_map

        user_id = _uid()

        with pytest.raises(ValueError):
            save_category_map(user_id, [["Food", "PIZZA"]])


# ---------------------------------------------------------------------------
# TestListCategories
# ---------------------------------------------------------------------------

class TestListCategories:
    def test_returns_empty_list_for_user_with_no_categories(self, app_ctx):
        """A new user with no categories must get an empty list."""
        from app.account_settings.services import list_categories

        result = list_categories(_uid())

        assert result == []

    def test_returns_categories_in_alphabetical_order(self, app_ctx):
        """Categories must be returned sorted by name ASC."""
        from app.account_settings.services import list_categories, save_category_map

        user_id = _uid()
        save_category_map(user_id, {
            "Zoning": [],
            "Apples": [],
            "Midpoint": [],
        })

        result = list_categories(user_id)
        names = [c["name"] for c in result]

        assert names == sorted(names), "Categories must be ordered by name ASC"

    def test_each_category_has_required_fields(self, app_ctx):
        """Each item in the list must have 'id', 'name', and 'keywords' fields."""
        from app.account_settings.services import list_categories, create_category

        user_id = _uid()
        create_category(user_id, "Groceries")

        result = list_categories(user_id)

        assert len(result) == 1
        cat = result[0]
        assert "id" in cat, "Category dict must include 'id'"
        assert "name" in cat, "Category dict must include 'name'"
        assert "keywords" in cat, "Category dict must include 'keywords'"
        assert isinstance(cat["id"], str)
        assert cat["name"] == "Groceries"
        assert isinstance(cat["keywords"], list)

    def test_keywords_within_category_are_alphabetical(self, app_ctx):
        """Keywords within a category must be sorted alphabetically."""
        from app.account_settings.services import (
            list_categories, create_category, add_keyword,
        )

        user_id = _uid()
        cat = create_category(user_id, "Groceries")
        cat_id = cat["id"]
        add_keyword(user_id, cat_id, "ZEHRS")
        add_keyword(user_id, cat_id, "LOBLAWS")
        add_keyword(user_id, cat_id, "METRO")

        result = list_categories(user_id)
        keywords = result[0]["keywords"]

        assert keywords == sorted(keywords), "Keywords must be ordered alphabetically"

    def test_second_call_within_request_context_returns_same_object(self, app_ctx):
        """Within a single Flask request context, the second call to
        list_categories must return the same Python object (cache hit) —
        no second DB query. This verifies the per-request caching contract."""
        from app import create_app
        from app.account_settings.services import list_categories, create_category

        user_id = _uid()
        app = create_app()
        app.config["TESTING"] = True

        with app.test_request_context("/"):
            create_category(user_id, "Cached Cat")
            first = list_categories(user_id)
            second = list_categories(user_id)

        assert first is second, (
            "Second list_categories call in same request context must return "
            "the same object (cache hit)"
        )


# ---------------------------------------------------------------------------
# TestCreateCategory
# ---------------------------------------------------------------------------

class TestCreateCategory:
    def test_happy_path_returns_dict_with_id_name_keywords(self, app_ctx):
        """Creating a valid category must return a dict with 'id', 'name',
        and 'keywords' (initially empty)."""
        from app.account_settings.services import create_category

        user_id = _uid()
        result = create_category(user_id, "Groceries")

        assert isinstance(result, dict)
        assert "id" in result
        assert result["name"] == "Groceries"
        assert result["keywords"] == []

    def test_normalizes_whitespace_in_name(self, app_ctx):
        """Name is stripped and internal whitespace collapsed before insert.
        '  Fast  Food  ' must return 'Fast Food'."""
        from app.account_settings.services import create_category

        user_id = _uid()
        result = create_category(user_id, "  Fast  Food  ")

        assert result["name"] == "Fast Food"

    def test_raises_for_empty_name(self, app_ctx):
        """Empty string name must raise ValueError('Category name cannot be empty')."""
        from app.account_settings.services import create_category

        user_id = _uid()

        with pytest.raises(ValueError, match="Category name cannot be empty"):
            create_category(user_id, "")

    def test_raises_for_whitespace_only_name(self, app_ctx):
        """Whitespace-only name must raise ValueError('Category name cannot be empty')."""
        from app.account_settings.services import create_category

        user_id = _uid()

        with pytest.raises(ValueError, match="Category name cannot be empty"):
            create_category(user_id, "   ")

    def test_raises_for_duplicate_name_same_user(self, app_ctx):
        """Creating a category with the same name for the same user must raise
        ValueError containing the category name."""
        from app.account_settings.services import create_category

        user_id = _uid()
        create_category(user_id, "Food")

        with pytest.raises(ValueError, match="Food"):
            create_category(user_id, "Food")

    def test_two_users_can_have_same_category_name(self, app_ctx):
        """The uniqueness constraint is per-user. Two different users can each
        have a category named 'Food' without conflict."""
        from app.account_settings.services import create_category

        user_a = _uid()
        user_b = _uid()

        result_a = create_category(user_a, "Food")
        result_b = create_category(user_b, "Food")

        assert result_a["name"] == "Food"
        assert result_b["name"] == "Food"
        assert result_a["id"] != result_b["id"]


# ---------------------------------------------------------------------------
# TestRenameCategory
# ---------------------------------------------------------------------------

class TestRenameCategory:
    def test_happy_path_returns_updated_dict(self, app_ctx):
        """Renaming a valid category must return {'id': ..., 'name': new_name}."""
        from app.account_settings.services import create_category, rename_category

        user_id = _uid()
        cat = create_category(user_id, "Eating Out")
        cat_id = cat["id"]

        result = rename_category(user_id, cat_id, "Restaurants")

        assert result["id"] == cat_id
        assert result["name"] == "Restaurants"

    def test_normalizes_whitespace_in_new_name(self, app_ctx):
        """New name is stripped before comparison and storage."""
        from app.account_settings.services import create_category, rename_category

        user_id = _uid()
        cat = create_category(user_id, "Old Name")

        result = rename_category(user_id, cat["id"], "  New  Name  ")

        assert result["name"] == "New Name"

    def test_raises_category_not_found_for_wrong_owner(self, app_ctx):
        """If the category_id does not belong to the given user_id, must raise
        ValueError('Category not found')."""
        from app.account_settings.services import create_category, rename_category

        owner = _uid()
        other = _uid()
        cat = create_category(owner, "Owner's Cat")

        with pytest.raises(ValueError, match="Category not found"):
            rename_category(other, cat["id"], "Stolen Name")

    def test_raises_for_empty_new_name(self, app_ctx):
        """Empty new_name must raise ValueError('Category name cannot be empty')."""
        from app.account_settings.services import create_category, rename_category

        user_id = _uid()
        cat = create_category(user_id, "Valid")

        with pytest.raises(ValueError, match="Category name cannot be empty"):
            rename_category(user_id, cat["id"], "")

    def test_raises_for_duplicate_name_conflict(self, app_ctx):
        """Renaming to a name that already exists for this user must raise
        ValueError containing the conflicting name."""
        from app.account_settings.services import create_category, rename_category

        user_id = _uid()
        cat_a = create_category(user_id, "Food")
        cat_b = create_category(user_id, "Transport")

        with pytest.raises(ValueError, match="Food"):
            rename_category(user_id, cat_b["id"], "Food")

    def test_self_rename_does_not_raise(self, app_ctx):
        """Renaming a category to its own current name must succeed — no
        self-conflict error."""
        from app.account_settings.services import create_category, rename_category

        user_id = _uid()
        cat = create_category(user_id, "Groceries")

        # Must not raise
        result = rename_category(user_id, cat["id"], "Groceries")

        assert result["name"] == "Groceries"


# ---------------------------------------------------------------------------
# TestDeleteCategory
# ---------------------------------------------------------------------------

class TestDeleteCategory:
    def test_raises_category_not_found_for_wrong_owner(self, app_ctx):
        """Deleting a category owned by another user must raise
        ValueError('Category not found')."""
        from app.account_settings.services import create_category, delete_category

        owner = _uid()
        attacker = _uid()
        cat = create_category(owner, "Owner's Category")

        with pytest.raises(ValueError, match="Category not found"):
            delete_category(attacker, cat["id"])

    def test_deleted_category_no_longer_in_list(self, app_ctx):
        """After delete_category, list_categories must not include the deleted
        category."""
        from app.account_settings.services import (
            create_category, delete_category, list_categories,
        )

        user_id = _uid()
        cat = create_category(user_id, "ToDelete")
        cat_id = cat["id"]

        delete_category(user_id, cat_id)

        names = [c["name"] for c in list_categories(user_id)]
        assert "ToDelete" not in names

    def test_delete_cascades_to_keywords(self, app_ctx):
        """Deleting a category must also remove all its keywords. No orphan
        rows must remain in category_keywords (ON DELETE CASCADE)."""
        import sqlalchemy as sa
        from app.account_settings.services import (
            create_category, add_keyword, delete_category,
        )

        user_id = _uid()
        cat = create_category(user_id, "CascadeTest")
        cat_id = cat["id"]
        add_keyword(user_id, cat_id, "ORPHAN")

        delete_category(user_id, cat_id)

        # Verify directly that no keyword rows remain for this category_id.
        engine = sa.create_engine(DATABASE_URL)
        with engine.connect() as conn:
            row = conn.execute(
                sa.text(
                    "SELECT COUNT(*) FROM category_keywords WHERE category_id = :cid"
                ),
                {"cid": cat_id},
            ).fetchone()
        assert row[0] == 0, "No keyword rows must remain after category delete (CASCADE)"


# ---------------------------------------------------------------------------
# TestAddKeyword
# ---------------------------------------------------------------------------

class TestAddKeyword:
    def test_happy_path_returns_dict_with_id_and_uppercased_keyword(self, app_ctx):
        """Adding a valid keyword must return {'id': ..., 'keyword': UPPERCASED}."""
        from app.account_settings.services import create_category, add_keyword

        user_id = _uid()
        cat = create_category(user_id, "Groceries")

        result = add_keyword(user_id, cat["id"], "loblaws")

        assert "id" in result
        assert result["keyword"] == "LOBLAWS"

    def test_strips_and_uppercases_keyword(self, app_ctx):
        """Keyword ' loblaws ' (with surrounding spaces) must be stored as
        'LOBLAWS'."""
        from app.account_settings.services import create_category, add_keyword

        user_id = _uid()
        cat = create_category(user_id, "Groceries")

        result = add_keyword(user_id, cat["id"], " loblaws ")

        assert result["keyword"] == "LOBLAWS"

    def test_raises_category_not_found_for_wrong_owner(self, app_ctx):
        """Adding a keyword to a category owned by another user must raise
        ValueError('Category not found')."""
        from app.account_settings.services import create_category, add_keyword

        owner = _uid()
        attacker = _uid()
        cat = create_category(owner, "Owner's Cat")

        with pytest.raises(ValueError, match="Category not found"):
            add_keyword(attacker, cat["id"], "KEYWORD")

    def test_raises_for_empty_keyword(self, app_ctx):
        """Empty/whitespace keyword must raise ValueError('Keyword cannot be empty')."""
        from app.account_settings.services import create_category, add_keyword

        user_id = _uid()
        cat = create_category(user_id, "Food")

        with pytest.raises(ValueError, match="Keyword cannot be empty"):
            add_keyword(user_id, cat["id"], "")

    def test_raises_for_whitespace_only_keyword(self, app_ctx):
        """Whitespace-only keyword must raise ValueError('Keyword cannot be empty')."""
        from app.account_settings.services import create_category, add_keyword

        user_id = _uid()
        cat = create_category(user_id, "Food")

        with pytest.raises(ValueError, match="Keyword cannot be empty"):
            add_keyword(user_id, cat["id"], "   ")

    def test_raises_for_duplicate_keyword_same_category(self, app_ctx):
        """Adding the same keyword twice to the same category must raise
        ValueError containing the keyword."""
        from app.account_settings.services import create_category, add_keyword

        user_id = _uid()
        cat = create_category(user_id, "Food")
        add_keyword(user_id, cat["id"], "PIZZA")

        with pytest.raises(ValueError, match="PIZZA"):
            add_keyword(user_id, cat["id"], "PIZZA")

    def test_duplicate_keyword_case_insensitive_raises(self, app_ctx):
        """'pizza' and 'PIZZA' normalize to the same keyword. Adding the
        lower-case version after the upper-case version must raise a duplicate
        error."""
        from app.account_settings.services import create_category, add_keyword

        user_id = _uid()
        cat = create_category(user_id, "Food")
        add_keyword(user_id, cat["id"], "PIZZA")

        with pytest.raises(ValueError, match="PIZZA"):
            add_keyword(user_id, cat["id"], "pizza")

    def test_same_keyword_in_different_categories_is_allowed(self, app_ctx):
        """The same keyword may appear in two different categories without
        conflict (uniqueness is per-category, not global)."""
        from app.account_settings.services import create_category, add_keyword

        user_id = _uid()
        cat_a = create_category(user_id, "Fast Food")
        cat_b = create_category(user_id, "Restaurants")

        # Must not raise
        add_keyword(user_id, cat_a["id"], "PIZZA HUT")
        add_keyword(user_id, cat_b["id"], "PIZZA HUT")


# ---------------------------------------------------------------------------
# TestRemoveKeyword
# ---------------------------------------------------------------------------

class TestRemoveKeyword:
    def test_raises_category_not_found_for_wrong_owner(self, app_ctx):
        """Removing a keyword from a category owned by another user must raise
        ValueError('Category not found')."""
        from app.account_settings.services import create_category, add_keyword, remove_keyword

        owner = _uid()
        attacker = _uid()
        cat = create_category(owner, "Owner's Cat")
        kw = add_keyword(owner, cat["id"], "KEYWORD")

        with pytest.raises(ValueError, match="Category not found"):
            remove_keyword(attacker, cat["id"], kw["id"])

    def test_raises_keyword_not_found_for_wrong_keyword_id(self, app_ctx):
        """A keyword_id that does not belong to the given category must raise
        ValueError('Keyword not found')."""
        from app.account_settings.services import create_category, add_keyword, remove_keyword

        user_id = _uid()
        cat = create_category(user_id, "Food")
        add_keyword(user_id, cat["id"], "PIZZA")

        bogus_keyword_id = str(uuid.uuid4())

        with pytest.raises(ValueError, match="Keyword not found"):
            remove_keyword(user_id, cat["id"], bogus_keyword_id)

    def test_removed_keyword_no_longer_in_list_categories(self, app_ctx):
        """After remove_keyword, the keyword must not appear in the subsequent
        list_categories result."""
        from app.account_settings.services import (
            create_category, add_keyword, remove_keyword, list_categories,
        )

        user_id = _uid()
        cat = create_category(user_id, "Food")
        kw = add_keyword(user_id, cat["id"], "REMOVED KW")

        remove_keyword(user_id, cat["id"], kw["id"])

        result = list_categories(user_id)
        keywords = result[0]["keywords"]
        assert "REMOVED KW" not in keywords


# ---------------------------------------------------------------------------
# TestImportFromJson
# ---------------------------------------------------------------------------

class TestImportFromJson:
    def test_happy_path_replaces_all_categories(self, app_ctx):
        """Importing a valid dict replaces all existing categories."""
        from app.account_settings.services import import_from_json, list_categories

        user_id = _uid()
        import_from_json(user_id, {"Food": ["PIZZA"], "Transport": ["UBER"]})

        names = [c["name"] for c in list_categories(user_id)]
        assert "Food" in names
        assert "Transport" in names

    def test_normalizes_names_and_keywords(self, app_ctx):
        """Import normalizes category names (strip + collapse whitespace) and
        keywords (strip + uppercase)."""
        from app.account_settings.services import import_from_json, list_categories

        user_id = _uid()
        import_from_json(user_id, {"  Fast  Food  ": [" pizza "]})

        result = list_categories(user_id)
        assert result[0]["name"] == "Fast Food"
        assert result[0]["keywords"] == ["PIZZA"]

    def test_is_idempotent(self, app_ctx):
        """Calling import_from_json twice with the same map must leave the
        database in the same state as calling it once."""
        from app.account_settings.services import import_from_json, list_categories

        user_id = _uid()
        category_map = {"Food": ["PIZZA"], "Transport": ["UBER"]}

        import_from_json(user_id, category_map)
        import_from_json(user_id, category_map)

        result = list_categories(user_id)
        names = [c["name"] for c in result]
        assert sorted(names) == ["Food", "Transport"]
        # No duplicates
        assert len(names) == 2

    def test_raises_for_non_dict_input(self, app_ctx):
        """A non-dict input must raise ValueError('Invalid category map format')."""
        from app.account_settings.services import import_from_json

        with pytest.raises(ValueError, match="Invalid category map format"):
            import_from_json(_uid(), ["Food", "Transport"])

    def test_raises_for_non_string_keys(self, app_ctx):
        """Dict with non-string keys must raise ValueError('Invalid category map format')."""
        from app.account_settings.services import import_from_json

        with pytest.raises(ValueError, match="Invalid category map format"):
            import_from_json(_uid(), {1: ["PIZZA"], 2: ["UBER"]})

    def test_raises_for_non_list_values(self, app_ctx):
        """Dict values that are not lists must raise ValueError('Invalid category map format')."""
        from app.account_settings.services import import_from_json

        with pytest.raises(ValueError, match="Invalid category map format"):
            import_from_json(_uid(), {"Food": "PIZZA"})

    def test_raises_for_non_string_elements_in_keyword_lists(self, app_ctx):
        """Lists containing non-strings must raise ValueError('Invalid category map format')."""
        from app.account_settings.services import import_from_json

        with pytest.raises(ValueError, match="Invalid category map format"):
            import_from_json(_uid(), {"Food": [123, 456]})


# ---------------------------------------------------------------------------
# TestSeedDefaults
# ---------------------------------------------------------------------------

class TestSeedDefaults:
    def test_seeds_categories_for_new_user(self, app_ctx):
        """For a user with no categories and a configured GENERIC_CATEGORY_MAP,
        seed_defaults must create categories."""
        from app import create_app
        from app.account_settings.services import seed_defaults, list_categories

        user_id = _uid()
        # Provide a non-empty seed map via config
        app = create_app()
        app.config["TESTING"] = True
        app.config["GENERIC_CATEGORY_MAP"] = {"Groceries": ["LOBLAWS"], "Transport": ["UBER"]}

        with app.app_context():
            seed_defaults(user_id)
            result = list_categories(user_id)

        names = [c["name"] for c in result]
        assert "Groceries" in names or len(names) > 0, (
            "seed_defaults must create at least one category from the configured map"
        )

    def test_no_op_if_user_already_has_categories(self, app_ctx):
        """seed_defaults must not overwrite existing categories. If the user
        already has categories, the call is a no-op."""
        from app.account_settings.services import (
            create_category, seed_defaults, list_categories,
        )

        user_id = _uid()
        create_category(user_id, "MyCustomCategory")

        # Seed again — must not change anything
        seed_defaults(user_id)

        names = [c["name"] for c in list_categories(user_id)]
        assert "MyCustomCategory" in names, (
            "Existing categories must survive seed_defaults no-op call"
        )

    def test_no_op_if_generic_category_map_not_configured(self, app_ctx):
        """If GENERIC_CATEGORY_MAP is empty or absent, seed_defaults must do
        nothing without raising."""
        from app import create_app
        from app.account_settings.services import seed_defaults, list_categories

        user_id = _uid()
        app = create_app()
        app.config["TESTING"] = True
        app.config["GENERIC_CATEGORY_MAP"] = {}

        with app.app_context():
            # Must not raise
            seed_defaults(user_id)
            result = list_categories(user_id)

        assert result == [], "No categories must be created when seed map is empty"

    def test_calling_seed_defaults_twice_is_idempotent(self, app_ctx):
        """Calling seed_defaults a second time must have no effect — the second
        call sees existing categories and is a no-op."""
        from app import create_app
        from app.account_settings.services import seed_defaults, list_categories

        user_id = _uid()
        app = create_app()
        app.config["TESTING"] = True
        app.config["GENERIC_CATEGORY_MAP"] = {"Food": ["PIZZA"]}

        with app.app_context():
            seed_defaults(user_id)
            first_count = len(list_categories(user_id))

            seed_defaults(user_id)
            second_count = len(list_categories(user_id))

        assert first_count == second_count, (
            "Second seed_defaults call must not add duplicate categories"
        )


# ---------------------------------------------------------------------------
# TestCacheInvalidation
# ---------------------------------------------------------------------------

class TestCacheInvalidation:
    def test_create_category_invalidates_list_cache(self, app_ctx):
        """Within one request context: list_categories → create_category →
        list_categories. The second list call must return the newly created
        category, proving the write invalidated the g-level cache."""
        from app import create_app
        from app.account_settings.services import list_categories, create_category

        user_id = _uid()
        app = create_app()
        app.config["TESTING"] = True

        with app.test_request_context("/"):
            first = list_categories(user_id)
            assert first == [], "Precondition: no categories yet"

            create_category(user_id, "New Category")

            second = list_categories(user_id)
            names = [c["name"] for c in second]
            assert "New Category" in names, (
                "list_categories after create_category must reflect the new "
                "category (cache must have been invalidated by the write)"
            )

    def test_delete_category_invalidates_list_cache(self, app_ctx):
        """Within one request context: create, list, delete, list. The final
        list must not include the deleted category."""
        from app import create_app
        from app.account_settings.services import (
            list_categories, create_category, delete_category,
        )

        user_id = _uid()
        app = create_app()
        app.config["TESTING"] = True

        with app.test_request_context("/"):
            cat = create_category(user_id, "Temp")
            list_categories(user_id)  # warm cache

            delete_category(user_id, cat["id"])

            after = list_categories(user_id)
            names = [c["name"] for c in after]
            assert "Temp" not in names, (
                "list_categories after delete_category must not return the "
                "deleted category (cache must have been invalidated)"
            )

    def test_add_keyword_invalidates_list_cache(self, app_ctx):
        """Within one request context: create, list (warm cache), add keyword,
        list again. The second list must include the new keyword."""
        from app import create_app
        from app.account_settings.services import (
            list_categories, create_category, add_keyword,
        )

        user_id = _uid()
        app = create_app()
        app.config["TESTING"] = True

        with app.test_request_context("/"):
            cat = create_category(user_id, "Food")
            list_categories(user_id)  # warm cache

            add_keyword(user_id, cat["id"], "PIZZA")

            after = list_categories(user_id)
            keywords = after[0]["keywords"]
            assert "PIZZA" in keywords, (
                "list_categories after add_keyword must reflect the new keyword "
                "(cache must have been invalidated)"
            )
