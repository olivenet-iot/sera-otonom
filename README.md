# Sera Otonom

![Version](https://img.shields.io/badge/version-0.1.0-blue)
![Python](https://img.shields.io/badge/python-3.10+-green)
![Tests](https://img.shields.io/badge/tests-229%20passing-brightgreen)
![License](https://img.shields.io/badge/license-MIT-orange)

AI-powered greenhouse automation system using Claude Code as the decision-making brain.

## Overview

Sera Otonom transforms traditional threshold-based greenhouse automation into an intelligent, proactive system that:

- **Analyzes** sensor data, weather forecasts, and trends
- **Reasons** about optimal conditions for plants
- **Decides** on proactive interventions
- **Explains** every decision in natural language

## Features

### AI Brain
- **SeraBrain Orchestrator** - Central decision engine with Claude Code integration
- **Fallback Decision Maker** - Threshold-based backup when AI is unavailable
- **Trend Analysis** - Linear regression for predicting sensor changes
- **Natural Language Reasoning** - Every decision explained in human-readable form

### Connectivity
- **LoRaWAN Integration** - Via The Things Stack (TTS) MQTT
- **Weather API** - OpenWeatherMap with retry logic and caching
- **Telegram Alerts** - Rate-limited notifications for critical events

### Control & Monitoring
- **Action Executor** - Device limits, intervals, and duration control
- **Relay Control** - Pump and fan management via downlink commands
- **Web Dashboard** - Real-time monitoring with TailwindCSS UI
- **REST API** - FastAPI backend with 10 endpoints

### Safety Features
- **Dry-run Mode** - Simulate without sending commands
- **Device Limits** - Maximum on-time per device
- **Action Intervals** - Minimum time between activations
- **Daily Reset Scheduler** - Automatic counter resets at midnight

## Architecture

```
                    ┌─────────────────────────────────────────────────────────┐
                    │                     SERA OTONOM                         │
                    └─────────────────────────────────────────────────────────┘
                                              │
        ┌─────────────────────────────────────┼─────────────────────────────────────┐
        │                                     │                                     │
        ▼                                     ▼                                     ▼
┌───────────────┐                   ┌─────────────────┐                   ┌─────────────────┐
│   CONNECTORS  │                   │      CORE       │                   │    PROCESSORS   │
├───────────────┤                   ├─────────────────┤                   ├─────────────────┤
│ TTS MQTT      │◄─────────────────►│   SeraBrain     │◄─────────────────►│ SensorProcessor │
│ (LoRaWAN)     │   sensor data     │   Orchestrator  │   processed data  │                 │
│               │                   │                 │                   │ TrendAnalyzer   │
│ Weather API   │◄─────────────────►│   Claude Runner │                   │ (regression)    │
│ (OpenWeather) │   forecast        │                 │                   └─────────────────┘
│               │                   │   Data Collector│
│ Telegram      │◄──────────────────│                 │
│ (alerts)      │   notifications   │   Scheduler     │
└───────────────┘                   └────────┬────────┘
                                             │
                                             │ decisions
                                             ▼
                                    ┌─────────────────┐
                                    │     ACTIONS     │
                                    ├─────────────────┤
                                    │   Executor      │──────► Relay Commands
                                    │   (limits,      │        (pump, fan)
                                    │    intervals)   │
                                    │                 │
                                    │   RelayControl  │──────► TTS Downlink
                                    └─────────────────┘

┌─────────────────────────────────────────────────────────────────────────────────┐
│                                 DATA FLOW                                       │
│                                                                                 │
│  Sensors ──► TTS (LoRaWAN) ──► MQTT ──► Brain ──► Claude ──► Actions ──► Relays │
└─────────────────────────────────────────────────────────────────────────────────┘
```

## Installation

### Prerequisites

- Python 3.10 or higher
- Claude Code CLI installed and configured
- The Things Stack (TTS) account with MQTT access
- OpenWeatherMap API key
- (Optional) Telegram bot for alerts

### Setup

```bash
# Clone repository
git clone <repo-url>
cd sera-otonom

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Linux/Mac
# or: venv\Scripts\activate  # Windows

# Install dependencies
pip install -r requirements.txt

# Copy environment template
cp .env.example .env

# Edit .env with your credentials
nano .env
```

## Environment Variables

Create a `.env` file with the following variables:

```bash
# TTS MQTT Configuration
TTS_MQTT_BROKER=eu1.cloud.thethings.network
TTS_MQTT_USERNAME=your-app-id@ttn
TTS_MQTT_PASSWORD=NNSXS.your-api-key
TTS_APP_ID=your-app-id

# Weather API
WEATHER_API_KEY=your-openweathermap-api-key

# Telegram Alerts (optional)
TELEGRAM_BOT_TOKEN=123456:ABC-your-bot-token
TELEGRAM_CHAT_ID=-1001234567890

# Device EUIs
SENSOR_TEMP_HUM_EUI=0000000000000001
SENSOR_SOIL_EUI=0000000000000002
SENSOR_LIGHT_EUI=0000000000000003
RELAY_PUMP_EUI=0000000000000010
RELAY_FAN_EUI=0000000000000011
```

## Usage

### CLI Commands

```bash
# Show version
python main.py --version

# Show system status
python main.py status

# Run single decision cycle (debug mode)
python main.py --once --debug

# Run without sending commands (dry-run)
python main.py --dry-run

# Run with fallback only (no Claude)
python main.py --no-claude

# Run continuous mode
python main.py

# Custom config file
python main.py --config path/to/settings.yaml
```

### CLI Options

| Option | Short | Description |
|--------|-------|-------------|
| `--version` | `-v` | Show version and exit |
| `--debug` | `-d` | Enable DEBUG level logging |
| `--dry-run` | | Simulate without sending commands |
| `--no-claude` | | Use fallback decision maker only |
| `--once` | | Run single cycle and exit |
| `--config` | `-c` | Custom config file path |

### Web Dashboard

```bash
# Start the API server (default: http://localhost:8080)
uvicorn ui.backend.main:app --host 0.0.0.0 --port 8080

# Or with auto-reload for development
uvicorn ui.backend.main:app --reload
```

Access the dashboard at `http://localhost:8080`

### API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/health` | API health check |
| `GET` | `/api/info` | System information |
| `GET` | `/api/brain/status` | Current brain status and devices |
| `GET` | `/api/brain/decisions` | Decision history (paginated) |
| `GET` | `/api/brain/decisions/{id}` | Get specific decision |
| `GET` | `/api/brain/thoughts` | Recent AI reasoning |
| `POST` | `/api/brain/ask` | Ask AI a question |
| `POST` | `/api/control/mode` | Change operation mode |
| `POST` | `/api/control/override` | Manual device control |
| `GET` | `/` | Web dashboard |

## Configuration

### settings.yaml

Main configuration file with system settings:

```yaml
app:
  name: "Sera Otonom"
  version: "0.1.0"
  environment: "development"

tts:
  mqtt:
    broker: "${TTS_MQTT_BROKER}"
    port: 8883
    use_tls: true
    username: "${TTS_MQTT_USERNAME}"
    password: "${TTS_MQTT_PASSWORD}"
    app_id: "${TTS_APP_ID}"

weather:
  provider: "openweathermap"
  api_key: "${WEATHER_API_KEY}"
  location:
    lat: 35.1856
    lon: 33.3823
  update_interval_minutes: 30

brain:
  cycle_interval_seconds: 300
  claude_timeout_seconds: 120
  max_retries: 3
  decision_limits:
    max_pump_duration_minutes: 60
    max_fan_duration_minutes: 120
    min_action_interval_minutes: 15

alerts:
  telegram:
    enabled: true
    bot_token: ${TELEGRAM_BOT_TOKEN}
    chat_id: ${TELEGRAM_CHAT_ID}
  rate_limit:
    max_per_hour: 10
    cooldown_seconds: 300
```

### thresholds.yaml

Fallback thresholds when AI is unavailable:

```yaml
temperature:
  optimal_range: [20, 28]
  warning_low: 15
  warning_high: 32
  critical_low: 10
  critical_high: 38

humidity:
  optimal_range: [60, 80]
  warning_low: 50
  warning_high: 90

soil_moisture:
  optimal_range: [40, 70]
  warning_low: 30
  warning_high: 80

action_intervals:
  defaults:
    pump: 15    # minutes between pump activations
    fan: 10     # minutes between fan activations
```

### devices.yaml

Sensor and relay definitions:

```yaml
sensors:
  temp_humidity_01:
    dev_eui: "${SENSOR_TEMP_HUM_EUI}"
    device_id: "sera-temp-hum-01"
    type: "temperature_humidity"
    measurements:
      - name: "temperature"
        unit: "°C"
      - name: "humidity"
        unit: "%"

relays:
  pump_01:
    dev_eui: "${RELAY_PUMP_EUI}"
    device_id: "sera-pump-01"
    type: "relay"
    control_type: "pump"
    max_on_duration_minutes: 60
    commands:
      "on": "AQ=="   # Base64 encoded
      "off": "AA=="
```

## Testing

```bash
# Run all tests
python -m pytest tests/ -v

# Run with coverage report
python -m pytest tests/ --cov=. --cov-report=term-missing

# Run specific test module
python -m pytest tests/test_brain.py -v
python -m pytest tests/test_executor.py -v
python -m pytest tests/test_api.py -v

# Run tests matching pattern
python -m pytest tests/ -k "weather" -v

# Quick test count
python -m pytest tests/ --collect-only -q
```

### Test Modules

| Module | Description |
|--------|-------------|
| `test_brain.py` | SeraBrain orchestrator tests |
| `test_executor.py` | Action executor and limits |
| `test_api.py` | FastAPI endpoint tests |
| `test_tts_mqtt.py` | MQTT connector tests |
| `test_processors.py` | Sensor and trend processing |
| `test_weather.py` | Weather API integration |
| `test_alerts.py` | Telegram alert system |
| `test_main.py` | CLI and main entry point |

## Project Structure

```
sera-otonom/
├── main.py                 # CLI entry point
├── requirements.txt        # Python dependencies
├── .env.example            # Environment template
│
├── config/                 # Configuration files
│   ├── settings.yaml       # Main settings
│   ├── devices.yaml        # Sensor/relay definitions
│   └── thresholds.yaml     # Fallback thresholds
│
├── core/                   # Core orchestration
│   ├── brain.py            # SeraBrain orchestrator
│   ├── claude_runner.py    # Claude Code integration
│   ├── data_collector.py   # Data aggregation
│   └── scheduler.py        # Daily reset scheduler
│
├── connectors/             # External integrations
│   ├── tts_mqtt.py         # TTS MQTT client
│   ├── tts_uplink.py       # Sensor data receiver
│   ├── tts_downlink.py     # Command sender
│   └── weather.py          # Weather API client
│
├── processors/             # Data processing
│   ├── sensor_processor.py # Sensor data validation
│   └── trend_analyzer.py   # Linear regression trends
│
├── actions/                # Output actions
│   ├── executor.py         # Action executor (limits)
│   ├── relay_control.py    # Relay command builder
│   └── alert.py            # Telegram notifications
│
├── prompts/                # AI agent prompts
│   └── sera_brain.md       # Claude decision prompt
│
├── state/                  # Runtime state (JSON)
│   ├── templates/          # Initial state templates
│   ├── current.json        # Current sensor values
│   ├── device_states.json  # Device on/off states
│   └── decisions.json      # Decision history
│
├── ui/                     # Web interface
│   ├── backend/            # FastAPI application
│   │   ├── main.py         # App entry point
│   │   ├── schemas.py      # Pydantic models
│   │   └── routes/         # API endpoints
│   └── frontend/           # HTML/JS/TailwindCSS
│       └── index.html      # Dashboard page
│
├── utils/                  # Utilities
│   ├── config_loader.py    # YAML config loader
│   └── state_manager.py    # JSON state persistence
│
├── logs/                   # Log files
│   └── sera.log            # Rotating log file
│
└── tests/                  # Test suite (229 tests)
    ├── test_brain.py
    ├── test_executor.py
    ├── test_api.py
    └── ...
```

## Development Guide

### Adding a New Sensor

1. Add sensor definition to `config/devices.yaml`:

```yaml
sensors:
  new_sensor_01:
    dev_eui: "${NEW_SENSOR_EUI}"
    device_id: "sera-new-sensor-01"
    type: "your_sensor_type"
    measurements:
      - name: "value_name"
        unit: "unit"
        decoded_field: "payload_field"
        valid_range: [min, max]
```

2. Add environment variable to `.env`:

```bash
NEW_SENSOR_EUI=0000000000000099
```

3. Optionally add thresholds to `config/thresholds.yaml`

### Adding a New Action

1. Add relay definition to `config/devices.yaml`:

```yaml
relays:
  new_device_01:
    dev_eui: "${NEW_DEVICE_EUI}"
    device_id: "sera-new-device-01"
    type: "relay"
    control_type: "custom"
    max_on_duration_minutes: 30
    downlink_port: 1
    commands:
      "on": "AQ=="
      "off": "AA=="
```

2. Add action intervals to `config/thresholds.yaml`:

```yaml
action_intervals:
  defaults:
    custom: 20  # minutes
```

3. Update the AI prompt in `prompts/sera_brain.md` to include the new device

### Running in Development

```bash
# Run with debug logging
python main.py --debug

# Run single cycle for testing
python main.py --once --debug --dry-run

# Run API with auto-reload
uvicorn ui.backend.main:app --reload --port 8080
```

## License

MIT License - See LICENSE file for details.

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/new-feature`)
3. Run tests (`python -m pytest tests/ -v`)
4. Commit changes (`git commit -m 'Add new feature'`)
5. Push to branch (`git push origin feature/new-feature`)
6. Open a Pull Request
