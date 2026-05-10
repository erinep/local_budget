$json = $input | ConvertFrom-Json
$tool = $json.tool_input

if ($tool.isolation -eq "worktree") {
    $cwd = (Get-Location).Path
    if ($tool.prompt -match [regex]::Escape($cwd)) {
        $msg = "WARN: Agent uses isolation:worktree but prompt references the main repo path ($cwd). " +
               "Output paths should be relative to the worktree root — absolute paths pointing back " +
               "to the main repo defeat isolation and cause collisions between parallel agents."
        Write-Host $msg
    }
}
