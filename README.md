# Sera Otonom

AI-powered greenhouse automation system using Claude Code as the decision-making brain.

## Overview

Sera Otonom transforms traditional threshold-based greenhouse automation into an intelligent, proactive system that:

- **Analyzes** sensor data, weather forecasts, and trends
- **Reasons** about optimal conditions for plants
- **Decides** on proactive interventions
- **Explains** every decision in natural language

## Architecture

```
Sensors --> TTS (LoRaWAN) --> MQTT --> Brain --> Claude Code --> Actions --> Relays
```

## Quick Start

### Prerequisites

- Python 3.11+
- Claude Code CLI installed
- TTS (The Things Stack) account
- Weather API key (OpenWeatherMap)

### Installation

```bash
# Clone repo
git clone <repo-url>
cd sera-otonom

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Linux/Mac
# or: venv\Scripts\activate  # Windows

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your credentials
```

### Configuration

1. Edit `config/settings.yaml` for general settings
2. Edit `config/devices.yaml` for your sensor/relay EUIs
3. Set API keys in `.env`

### Running

```bash
# Start the brain
python -m core.brain

# Start UI (separate terminal)
python -m ui.backend.main
```

## Project Structure

```
sera-otonom/
├── config/          # Configuration files
├── core/            # Main orchestration
├── connectors/      # External system integrations
├── processors/      # Data processing
├── actions/         # Output actions
├── prompts/         # AI agent prompts
├── state/           # Runtime state (JSON)
│   └── templates/   # Initial state templates
├── ui/              # Web dashboard
└── tests/           # Test suite
```

## Development Status

- [x] Phase 1: Basic structure
- [ ] Phase 2: TTS Integration
- [ ] Phase 3: Data Processing
- [ ] Phase 4: Brain (Claude Code)
- [ ] Phase 5: Executor
- [ ] Phase 6: UI Dashboard
- [ ] Phase 7: Testing & Demo

## License

Private - Olivenet Ltd.
