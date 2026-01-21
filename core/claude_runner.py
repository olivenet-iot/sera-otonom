"""
Sera Otonom - Claude Code Runner

Claude Code CLI'ı çağıran modül
"""

import subprocess
import asyncio
import logging
import json
import re
from typing import Optional, Any
from pathlib import Path
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class ClaudeResponse:
    """Claude Code yanıt yapısı"""
    success: bool
    raw_output: str = ""
    analysis: Optional[dict] = None
    decision: Optional[dict] = None
    reasoning: str = ""
    error: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    execution_time_ms: int = 0


class ClaudeRunner:
    """Claude Code CLI wrapper"""

    def __init__(self, timeout: int = 120, max_retries: int = 3):
        """
        Claude Runner'ı başlat

        Args:
            timeout: Maksimum çalışma süresi (saniye)
            max_retries: Hata durumunda tekrar deneme sayısı
        """
        self.timeout = timeout
        self.max_retries = max_retries
        self.prompt_template_path = Path("prompts/sera_agent.md")
        self._system_prompt: Optional[str] = None
        logger.info("ClaudeRunner initialized")

    def _load_system_prompt(self) -> str:
        """Sistem prompt'unu yükle (lazy loading)"""
        if self._system_prompt is None:
            try:
                with open(self.prompt_template_path, 'r', encoding='utf-8') as f:
                    self._system_prompt = f.read()
                logger.debug("Loaded system prompt from sera_agent.md")
            except FileNotFoundError:
                logger.warning(f"System prompt not found: {self.prompt_template_path}")
                self._system_prompt = "Sen bir sera yönetim AI agent'ısın."
        return self._system_prompt

    def build_prompt(self, context: dict) -> str:
        """
        Analiz için prompt oluştur

        Args:
            context: Sensör verileri, hava tahmini vb.

        Returns:
            Claude Code'a gönderilecek prompt
        """
        system_prompt = self._load_system_prompt()

        # Context'i JSON formatında ekle
        context_json = json.dumps(context, indent=2, ensure_ascii=False)

        prompt = f"""{system_prompt}

---

## GÜNCEL VERİLER

```json
{context_json}
```

---

Yukarıdaki verileri analiz et ve karar ver. Çıktını mutlaka belirtilen JSON formatında ver.
"""
        return prompt

    async def run(self, context: dict) -> ClaudeResponse:
        """
        Claude Code'u çağır

        Args:
            context: Sensör verileri, hava tahmini vb.

        Returns:
            ClaudeResponse objesi
        """
        prompt = self.build_prompt(context)

        for attempt in range(self.max_retries):
            try:
                logger.info(f"Running Claude Code (attempt {attempt + 1}/{self.max_retries})")
                start_time = datetime.now()

                raw_output = await self._execute_claude(prompt)

                execution_time = int((datetime.now() - start_time).total_seconds() * 1000)

                response = self.parse_response(raw_output)
                response.execution_time_ms = execution_time

                if response.success:
                    logger.info(f"Claude Code succeeded in {execution_time}ms")
                    return response

                # Parse başarısız, retry
                logger.warning(f"Parse failed on attempt {attempt + 1}: {response.error}")

            except asyncio.TimeoutError:
                logger.error(f"Claude Code timeout on attempt {attempt + 1}")
            except Exception as e:
                logger.error(f"Claude Code error on attempt {attempt + 1}: {e}")

        # Tüm denemeler başarısız
        return ClaudeResponse(
            success=False,
            error=f"All {self.max_retries} attempts failed",
            raw_output=""
        )

    async def _execute_claude(self, prompt: str) -> str:
        """
        Subprocess ile Claude Code CLI çalıştır

        Args:
            prompt: Gönderilecek prompt

        Returns:
            Ham CLI çıktısı
        """
        cmd = [
            "claude",
            "-p", prompt,
            "--output-format", "text",
            "--max-turns", "1"
        ]

        # Run subprocess asynchronously
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=self.timeout
            )

            if process.returncode != 0:
                error_msg = stderr.decode('utf-8', errors='replace')
                logger.error(f"Claude CLI error: {error_msg}")
                raise RuntimeError(f"Claude CLI failed: {error_msg}")

            return stdout.decode('utf-8', errors='replace')

        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            raise

    def parse_response(self, raw_output: str) -> ClaudeResponse:
        """
        Claude çıktısını parse et

        Args:
            raw_output: Ham CLI çıktısı

        Returns:
            ClaudeResponse objesi
        """
        if not raw_output.strip():
            return ClaudeResponse(
                success=False,
                raw_output=raw_output,
                error="Empty response from Claude"
            )

        # JSON bloğunu bul (```json ... ``` veya sadece {...})
        json_match = re.search(r'```json\s*([\s\S]*?)\s*```', raw_output)
        if json_match:
            json_str = json_match.group(1)
        else:
            # Doğrudan JSON objesi ara
            json_match = re.search(r'\{[\s\S]*"decision"[\s\S]*\}', raw_output)
            if json_match:
                json_str = json_match.group(0)
            else:
                return ClaudeResponse(
                    success=False,
                    raw_output=raw_output,
                    error="No JSON block found in response"
                )

        try:
            parsed = json.loads(json_str)
        except json.JSONDecodeError as e:
            return ClaudeResponse(
                success=False,
                raw_output=raw_output,
                error=f"JSON parse error: {e}"
            )

        # Beklenen alanları çıkar
        analysis = parsed.get("analysis")
        decision = parsed.get("decision")
        next_check = parsed.get("next_check")

        if not decision:
            return ClaudeResponse(
                success=False,
                raw_output=raw_output,
                error="No 'decision' field in response"
            )

        # Reasoning oluştur
        reasoning = self._build_reasoning(analysis, decision)

        return ClaudeResponse(
            success=True,
            raw_output=raw_output,
            analysis=analysis,
            decision=decision,
            reasoning=reasoning
        )

    def _build_reasoning(self, analysis: Optional[dict], decision: Optional[dict]) -> str:
        """
        İnsan okunabilir reasoning oluştur

        Args:
            analysis: Analiz dict'i
            decision: Karar dict'i

        Returns:
            Reasoning string
        """
        parts = []

        if analysis:
            summary = analysis.get("summary", "")
            if summary:
                parts.append(f"Durum: {summary}")

            concerns = analysis.get("concerns", [])
            if concerns:
                parts.append(f"Endişeler: {', '.join(concerns)}")

            positive = analysis.get("positive", [])
            if positive:
                parts.append(f"Olumlu: {', '.join(positive)}")

        if decision:
            action = decision.get("action", "none")
            reason = decision.get("reason", "")
            confidence = decision.get("confidence", 0)

            parts.append(f"Karar: {action}")
            if reason:
                parts.append(f"Sebep: {reason}")
            parts.append(f"Güven: %{int(confidence * 100)}")

        return " | ".join(parts) if parts else "Reasoning oluşturulamadı"


class FallbackDecisionMaker:
    """Claude çalışmazsa threshold-based kararlar"""

    def __init__(self, threshold_config: dict):
        """
        Fallback karar vericiyi başlat

        Args:
            threshold_config: thresholds.yaml içeriği
        """
        self.thresholds = threshold_config
        logger.info("FallbackDecisionMaker initialized")

    def make_decision(self, sensor_data: dict) -> ClaudeResponse:
        """
        Threshold'lara göre karar ver

        Args:
            sensor_data: Sensör verileri

        Returns:
            ClaudeResponse formatında karar
        """
        actions = []
        concerns = []

        # Temperature check
        temp = sensor_data.get("temperature", {}).get("value")
        if temp is not None:
            temp_thresh = self.thresholds.get("temperature", {})
            if temp >= temp_thresh.get("critical_high", 38):
                actions.append({
                    "device": "fan_01",
                    "action": "fan_on",
                    "reason": f"Kritik sıcaklık: {temp}°C"
                })
                concerns.append(f"Kritik sıcaklık ({temp}°C)")
            elif temp >= temp_thresh.get("warning_high", 32):
                actions.append({
                    "device": "fan_01",
                    "action": "fan_on",
                    "reason": f"Yüksek sıcaklık: {temp}°C"
                })
                concerns.append(f"Yüksek sıcaklık ({temp}°C)")
            elif temp <= temp_thresh.get("warning_low", 15):
                actions.append({
                    "device": "fan_01",
                    "action": "fan_off",
                    "reason": f"Düşük sıcaklık: {temp}°C"
                })

        # Humidity check
        humidity = sensor_data.get("humidity", {}).get("value")
        if humidity is not None:
            hum_thresh = self.thresholds.get("humidity", {})
            if humidity >= hum_thresh.get("warning_high", 90):
                actions.append({
                    "device": "fan_01",
                    "action": "fan_on",
                    "reason": f"Yüksek nem: %{humidity}"
                })
                concerns.append(f"Yüksek nem (%{humidity})")

        # Soil moisture check
        soil = sensor_data.get("soil_moisture", {}).get("value")
        if soil is not None:
            soil_thresh = self.thresholds.get("soil_moisture", {})
            if soil <= soil_thresh.get("critical_low", 20):
                actions.append({
                    "device": "pump_01",
                    "action": "pump_on",
                    "duration_minutes": 15,
                    "reason": f"Kritik toprak nemi: %{soil}"
                })
                concerns.append(f"Kritik toprak nemi (%{soil})")
            elif soil <= soil_thresh.get("warning_low", 30):
                actions.append({
                    "device": "pump_01",
                    "action": "pump_on",
                    "duration_minutes": 10,
                    "reason": f"Düşük toprak nemi: %{soil}"
                })
                concerns.append(f"Düşük toprak nemi (%{soil})")
            elif soil >= soil_thresh.get("warning_high", 80):
                actions.append({
                    "device": "pump_01",
                    "action": "pump_off",
                    "reason": f"Yüksek toprak nemi: %{soil}"
                })

        # En öncelikli aksiyonu seç
        if actions:
            primary_action = actions[0]
            decision = {
                "action": primary_action.get("action"),
                "device": primary_action.get("device"),
                "duration_minutes": primary_action.get("duration_minutes"),
                "reason": primary_action.get("reason"),
                "confidence": 0.7  # Fallback her zaman %70 güven
            }
        else:
            decision = {
                "action": "none",
                "device": None,
                "duration_minutes": None,
                "reason": "Tüm değerler normal aralıkta",
                "confidence": 0.8
            }

        analysis = {
            "summary": "Fallback threshold kontrolü",
            "concerns": concerns,
            "positive": [] if concerns else ["Tüm değerler normal"]
        }

        reasoning = self._build_reasoning(concerns, decision)

        return ClaudeResponse(
            success=True,
            raw_output="[Fallback Decision]",
            analysis=analysis,
            decision=decision,
            reasoning=reasoning
        )

    def _build_reasoning(self, concerns: list, decision: dict) -> str:
        """Reasoning string oluştur"""
        parts = ["[FALLBACK MODE]"]

        if concerns:
            parts.append(f"Endişeler: {', '.join(concerns)}")
        else:
            parts.append("Tüm değerler normal")

        parts.append(f"Karar: {decision.get('action', 'none')}")
        if decision.get('reason'):
            parts.append(f"Sebep: {decision['reason']}")

        return " | ".join(parts)


if __name__ == "__main__":
    import asyncio

    async def test():
        runner = ClaudeRunner()
        print(f"ClaudeRunner initialized: {runner}")

        # Test prompt building
        context = {
            "sensors": {
                "temperature": {"value": 28, "status": "normal"},
                "humidity": {"value": 65, "status": "normal"},
                "soil_moisture": {"value": 45, "status": "normal"}
            },
            "weather_forecast": {
                "tomorrow": {"temp_max": 35, "condition": "sunny"}
            }
        }
        prompt = runner.build_prompt(context)
        print(f"\nPrompt length: {len(prompt)} chars")

        # Test fallback
        fallback = FallbackDecisionMaker({
            "temperature": {"warning_high": 32, "critical_high": 38},
            "humidity": {"warning_high": 90},
            "soil_moisture": {"warning_low": 30, "critical_low": 20}
        })

        result = fallback.make_decision({
            "temperature": {"value": 35},
            "humidity": {"value": 70},
            "soil_moisture": {"value": 25}
        })
        print(f"\nFallback result: {result}")

    asyncio.run(test())
