# Hermes Agent Skill: ocas-finch

This directory contains the ocas-finch skill for [Hermes Agent](https://github.com/indigokarasu/hermes-agent).

## Installation

Copy this directory to your Hermes skills folder:

```bash
cp -r ocas-finch ~/.hermes/skills/
```

Or clone directly:

```bash
git clone https://github.com/indigokarasu/ocas-finch.git ~/.hermes/skills/ocas-finch
```

## Self-update

The skill includes a scheduled update mechanism via Hermes cron. To manually update:

```bash
cd ~/.hermes/skills/ocas-finch && git pull
```
