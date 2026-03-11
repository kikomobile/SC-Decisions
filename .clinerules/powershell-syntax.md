## Brief overview
This rule file provides guidelines for Windows PowerShell compatibility when writing commands and scripts in this project. These rules ensure commands execute correctly in the Windows PowerShell environment used in this workspace.

## PowerShell command syntax
- NEVER use `&&` as a statement separator in PowerShell commands
- Use semicolon `;` to chain commands: `command1 ; command2`
- If the second command should only run on success of the first, use: `if ($?) { command2 }` after `command1`
- Alternatively, run commands via cmd: `cmd /c "command1 && command2"` when `&&` is required
- Always test PowerShell commands in the actual environment before assuming they work

## Command execution patterns
- For conditional execution: `command1 ; if ($?) { command2 }`
- For sequential execution: `command1 ; command2 ; command3`
- When using cd/pushd commands: `cd directory ; python script.py`
- For complex command chains, consider writing a PowerShell script file instead of one-liners

## Error handling
- Check exit codes using `$?` variable (True if last command succeeded)
- Use `try/catch` blocks in PowerShell scripts for robust error handling
- When executing external commands, be aware that PowerShell may have different error behavior than cmd

## Examples
- **Incorrect**: `cd directory && python script.py`
- **Correct**: `cd directory ; python script.py`
- **Correct with conditional**: `cd directory ; if ($?) { python script.py }`
- **Correct using cmd**: `cmd /c "cd directory && python script.py"`

## Testing
- Always test PowerShell commands in the actual Windows PowerShell environment
- Be aware of execution policy restrictions that may affect script execution
- Consider using `-ExecutionPolicy Bypass` flag when running scripts if needed