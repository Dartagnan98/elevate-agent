---
sidebar_position: 7
---

# Profile Commands Reference

This page covers all commands related to [Elevate profiles](../user-guide/profiles.md). For general CLI commands, see [CLI Commands Reference](./cli-commands.md).

## `elevate profile`

```bash
elevate profile <subcommand>
```

Top-level command for managing profiles. Running `elevate profile` without a subcommand shows help.

| Subcommand | Description |
|------------|-------------|
| `list` | List all profiles. |
| `use` | Set the active (default) profile. |
| `create` | Create a new profile. |
| `delete` | Delete a profile. |
| `show` | Show details about a profile. |
| `alias` | Regenerate the shell alias for a profile. |
| `rename` | Rename a profile. |
| `export` | Export a profile to a tar.gz archive. |
| `import` | Import a profile from a tar.gz archive. |

## `elevate profile list`

```bash
elevate profile list
```

Lists all profiles. The currently active profile is marked with `*`.

**Example:**

```bash
$ elevate profile list
  default
* work
  dev
  personal
```

No options.

## `elevate profile use`

```bash
elevate profile use <name>
```

Sets `<name>` as the active profile. All subsequent `elevate` commands (without `-p`) will use this profile.

| Argument | Description |
|----------|-------------|
| `<name>` | Profile name to activate. Use `default` to return to the base profile. |

**Example:**

```bash
elevate profile use work
elevate profile use default
```

## `elevate profile create`

```bash
elevate profile create <name> [options]
```

Creates a new profile.

| Argument / Option | Description |
|-------------------|-------------|
| `<name>` | Name for the new profile. Must be a valid directory name (alphanumeric, hyphens, underscores). |
| `--clone` | Copy `config.yaml`, `.env`, and `SOUL.md` from the current profile. |
| `--clone-all` | Copy everything (config, memories, skills, sessions, state) from the current profile. |
| `--clone-from <profile>` | Clone from a specific profile instead of the current one. Used with `--clone` or `--clone-all`. |
| `--no-alias` | Skip wrapper script creation. |

Creating a profile does **not** make that profile directory the default project/workspace directory for terminal commands. If you want a profile to start in a specific project, set `terminal.cwd` in that profile's `config.yaml`.

**Examples:**

```bash
# Blank profile — needs full setup
elevate profile create mybot

# Clone config only from current profile
elevate profile create work --clone

# Clone everything from current profile
elevate profile create backup --clone-all

# Clone config from a specific profile
elevate profile create work2 --clone --clone-from work
```

## `elevate profile delete`

```bash
elevate profile delete <name> [options]
```

Deletes a profile and removes its shell alias.

| Argument / Option | Description |
|-------------------|-------------|
| `<name>` | Profile to delete. |
| `--yes`, `-y` | Skip confirmation prompt. |

**Example:**

```bash
elevate profile delete mybot
elevate profile delete mybot --yes
```

:::warning
This permanently deletes the profile's entire directory including all config, memories, sessions, and skills. Cannot delete the currently active profile.
:::

## `elevate profile show`

```bash
elevate profile show <name>
```

Displays details about a profile including its home directory, configured model, gateway status, skills count, and configuration file status.

This shows the profile's Elevate home directory, not the terminal working directory. Terminal commands start from `terminal.cwd` (or the launch directory on the local backend when `cwd: "."`).

| Argument | Description |
|----------|-------------|
| `<name>` | Profile to inspect. |

**Example:**

```bash
$ elevate profile show work
Profile: work
Path:    ~/.elevate/profiles/work
Model:   anthropic/claude-sonnet-4 (anthropic)
Gateway: stopped
Skills:  12
.env:    exists
SOUL.md: exists
Alias:   ~/.local/bin/work
```

## `elevate profile alias`

```bash
elevate profile alias <name> [options]
```

Regenerates the shell alias script at `~/.local/bin/<name>`. Useful if the alias was accidentally deleted or if you need to update it after moving your Elevate installation.

| Argument / Option | Description |
|-------------------|-------------|
| `<name>` | Profile to create/update the alias for. |
| `--remove` | Remove the wrapper script instead of creating it. |
| `--name <alias>` | Custom alias name (default: profile name). |

**Example:**

```bash
elevate profile alias work
# Creates/updates ~/.local/bin/work

elevate profile alias work --name mywork
# Creates ~/.local/bin/mywork

elevate profile alias work --remove
# Removes the wrapper script
```

## `elevate profile rename`

```bash
elevate profile rename <old-name> <new-name>
```

Renames a profile. Updates the directory and shell alias.

| Argument | Description |
|----------|-------------|
| `<old-name>` | Current profile name. |
| `<new-name>` | New profile name. |

**Example:**

```bash
elevate profile rename mybot assistant
# ~/.elevate/profiles/mybot → ~/.elevate/profiles/assistant
# ~/.local/bin/mybot → ~/.local/bin/assistant
```

## `elevate profile export`

```bash
elevate profile export <name> [options]
```

Exports a profile as a compressed tar.gz archive.

| Argument / Option | Description |
|-------------------|-------------|
| `<name>` | Profile to export. |
| `-o`, `--output <path>` | Output file path (default: `<name>.tar.gz`). |

**Example:**

```bash
elevate profile export work
# Creates work.tar.gz in the current directory

elevate profile export work -o ./work-2026-03-29.tar.gz
```

## `elevate profile import`

```bash
elevate profile import <archive> [options]
```

Imports a profile from a tar.gz archive.

| Argument / Option | Description |
|-------------------|-------------|
| `<archive>` | Path to the tar.gz archive to import. |
| `--name <name>` | Name for the imported profile (default: inferred from archive). |

**Example:**

```bash
elevate profile import ./work-2026-03-29.tar.gz
# Infers profile name from the archive

elevate profile import ./work-2026-03-29.tar.gz --name work-restored
```

## `elevate -p` / `elevate --profile`

```bash
elevate -p <name> <command> [options]
elevate --profile <name> <command> [options]
```

Global flag to run any Elevate command under a specific profile without changing the sticky default. This overrides the active profile for the duration of the command.

| Option | Description |
|--------|-------------|
| `-p <name>`, `--profile <name>` | Profile to use for this command. |

**Examples:**

```bash
elevate -p work chat -q "Check the server status"
elevate --profile dev gateway start
elevate -p personal skills list
elevate -p work config edit
```

## `elevate completion`

```bash
elevate completion <shell>
```

Generates shell completion scripts. Includes completions for profile names and profile subcommands.

| Argument | Description |
|----------|-------------|
| `<shell>` | Shell to generate completions for: `bash` or `zsh`. |

**Examples:**

```bash
# Install completions
elevate completion bash >> ~/.bashrc
elevate completion zsh >> ~/.zshrc

# Reload shell
source ~/.bashrc
```

After installation, tab completion works for:
- `elevate profile <TAB>` — subcommands (list, use, create, etc.)
- `elevate profile use <TAB>` — profile names
- `elevate -p <TAB>` — profile names

## See also

- [Profiles User Guide](../user-guide/profiles.md)
- [CLI Commands Reference](./cli-commands.md)
- [FAQ — Profiles section](./faq.md#profiles)
