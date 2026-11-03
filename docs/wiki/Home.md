# qbt-rules

**Stop babysitting your torrents.** qbt-rules is a client-server automation engine that watches qBittorrent and reacts to events, on a schedule, or on demand — categorizing, tagging, cleaning up, and re-prioritizing torrents so you don't have to.

```yaml
- id: delete-well-seeded-torrents
  meta:
    description: "Delete well-seeded torrents automatically"
  context: weekly-cleanup
  conditions:
    all:
      - field: info.ratio
        operator: ">="
        value: 2.0
  actions:
    - type: delete_torrent
      params:
        delete_files: false
```

That's a real, complete rule — no code, just YAML. A few things people actually use it for:

- 🎬 **Auto-categorize** new downloads by name pattern the moment they're added
- 🧹 **Clean up** anything that's hit ratio/seeding-time targets, on whatever schedule you want
- 🔒 **Block or quarantine** unwanted file types before they finish downloading
- 📊 **Enforce ratio rules** on private trackers without checking in manually
- ⏫ **Re-prioritize** the queue when something urgent lands

One Docker container, one YAML file, and qBittorrent does the rest. **[Get started in 5 minutes →](Quick-Start)**

## Table of Contents

- [Introduction](Introduction)
- [Quick Start](Quick-Start)
- [Rules Architecture](Rules-Architecture)
- [Contexts](Contexts)
- [Conditions](Conditions)
- [Available Fields](Available-Fields)
- [Actions](Actions)
- [Reusable References](Reusable-References)
- [HTTP API Reference](HTTP-API-Reference)
- [CLI Reference](CLI-Reference)
- [Dashboard](Dashboard)
- [Metrics](Metrics)
- [Security](Security)
- [In-Depth Configuration](In-Depth-Configuration)
- [Deployment](Deployment)
- [Scheduling](Scheduling)
- [Examples](Examples)
- [Advanced Rules Example](Advanced-Rules-Example)
- [Advanced Topics](Advanced-Topics)
- [Frequently Asked Questions](Frequently-Asked-Questions)
- [Troubleshooting](Troubleshooting)
- **For Developers**
  - [Contributing](Contributing)
  - [Architecture Internals](Architecture-Internals)
  - [Extending the Engine](Extending-the-Engine)
  - [Testing Guide](Testing-Guide)
  - [Release Process](Release-Process)
- [License](License)
