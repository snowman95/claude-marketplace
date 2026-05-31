# snowman95's Claude Code Marketplace

Personal marketplace for sharing Claude Code skills and plugins across multiple machines.

## Install on a new machine

```
/plugin marketplace add snowman95/claude-marketplace
/plugin install <plugin-name>@snowman95-marketplace
```

## Update on an existing machine

```
/plugin marketplace update snowman95-marketplace
```

## Adding a new plugin

1. Create a new directory under `plugins/<plugin-name>/`
2. Add `.claude-plugin/plugin.json`:
   ```json
   {
     "name": "<plugin-name>",
     "version": "0.1.0",
     "description": "..."
   }
   ```
3. Add skills under `plugins/<plugin-name>/skills/<skill-name>/SKILL.md`
4. Register the plugin in `.claude-plugin/marketplace.json` by adding an entry to the `plugins` array:
   ```json
   {
     "name": "<plugin-name>",
     "description": "...",
     "source": "./plugins/<plugin-name>"
   }
   ```
5. Commit and push. On each machine: `/plugin marketplace update snowman95-marketplace` then `/plugin install <plugin-name>@snowman95-marketplace`.
