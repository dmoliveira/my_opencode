# Notification Personalization

This repo supports notification personalization in the gateway and `/notify` controls with:

- Nerd icon + emoji fallback prefixes per event type (`complete`, `error`, `permission`, `question`)
- Versioned notification image assets (`assets/notify-icons/<version>/<event>.png`)
- Sound themes and event-level sound theme overrides

## Defaults

- Notify message style defaults to `brief`
- Nerd icon fallback strategy defaults to `nerd+emoji`
- Sound theme defaults to `classic`
- Icon pack version defaults to `v1`

## Notify Commands

- Set global sound theme:

```bash
python3 scripts/notify_command.py sound-theme classic
```

- Override sound theme for one event:

```bash
python3 scripts/notify_command.py event-sound error urgent
```

- Set icon pack version:

```bash
python3 scripts/notify_command.py icon-version v1
```

## Icon Generation Workflow

Generate candidates and a reference grid for each event:

```bash
make notify-icons-generate NOTIFY_ICON_VERSION=v1
```

Select a winning candidate (1-based index):

```bash
make notify-icons-select NOTIFY_ICON_VERSION=v1 EVENT=error CANDIDATE=2
```

The selector updates:

- `assets/notify-icons/<version>/<event>.png`
- `assets/notify-icons/<version>/manifest.json`

Re-running generation with a new version (for example `v2`) keeps previous versions intact and git-trackable.
