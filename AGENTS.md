# Notes for agents working on LabConstrictor-napari

The README says what the plugin is; [docs/REFERENCE.md](docs/REFERENCE.md) has the technical rules, the tests, linting and releasing.

## Documentation

Each topic of the LabConstrictor ecosystem has exactly one owner page, and every other page links to it instead of copying it. The owner table is "Sources of truth" in [LabConstrictor-Site's AGENTS.md](https://github.com/CellMigrationLab/LabConstrictor-Site/blob/main/AGENTS.md#sources-of-truth).

- This repository owns the **napari guide**, [docs/user-guide.md](docs/user-guide.md): how to install the plugin, open it, check that it worked, and what to do when something does not work. The Site publishes it at <https://cellmigrationlab.github.io/LabConstrictor-Site/guides/napari/>.
- It is the only page with the user install command and the current version numbers (of the plugin and of LabConstrictor-Tools). Update them there after a release; every other page, here or in other repositories, links to the guide.
- The Site fetches the guide, so its links and pictures must be absolute addresses, and its first heading is the menu title.
- Write in the Site's style ([DESIGN.md](https://github.com/CellMigrationLab/LabConstrictor-Site/blob/main/DESIGN.md)): sentence case, plain words, link text that says where it goes.
- A developer procedure (running the tests, releasing) may keep the commands it needs, but not the user install command.
