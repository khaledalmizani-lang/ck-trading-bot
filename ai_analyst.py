"""
CK Crypto Bot — AI Analyst
"""
import json
import config


def analyze_signal(symbol: str, direction: str, rsi: float,
                   confirmations: int, mtf_signals: dict) -> dict:
    if not config.AI_ENABLED or not config.ANTHROPIC_API_KEY:
        return _local(symbol, rsi, confirmations, mtf_signals)
    try:
        import urllib.request, ssl
        ctx = ssl.create_default_context()
        mtf_str = " | ".join([f"{tf}:{sig}" for tf, sig in mtf_signals.items()])
        prompt = f"""Analyze this Binance Spot BUY signal:
Symbol: {symbol}
RSI: {rsi}
Confirmations: {confirmations}/5
MTF: {mtf_str}
Respond ONLY with JSON: {{"verdict":"APPROVE","conviction":8,"risk":3,"reason":"brief"}}"""
        data = json.dumps({
            "model": "claude-sonnet-4-20250514",
            "max_tokens": 100,
            "messages": [{"role": "user", "content": prompt}]
        }).encode()
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages", data=data,
            headers={"Content-Type": "application/json", "x-api-key": config.ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
            body = json.loads(resp.read())
            text = body["content"][0]["text"].strip().replace("```json","").replace("```","")
            result = json.loads(text)
            conviction = int(result.get("conviction", 5))
            risk = int(result.get("risk", 5))
            verdict = result.get("verdict", "APPROVE")
            if conviction < config.AI_MIN_CONVICTION or risk > config.AI_MAX_RISK:
                verdict = "REJECT"
            print(f"[AI] {symbol} → {verdict} (C:{conviction} R:{risk})")
            return {"verdict": verdict, "conviction": conviction, "risk": risk, "reason": result.get("reason", "")}
    except Exception as e:
        print(f"[AI] Error: {e}")
        return _local(symbol, rsi, confirmations, mtf_signals)


def _local(symbol, rsi, confirmations, mtf_signals):
    conviction = min(confirmations * 2, 10)
    risk = 5
    signals = list(mtf_signals.values())
    if len(set(signals)) > 1:
        return {"verdict": "REJECT", "conviction": conviction, "risk": 9, "reason": "MTF conflict"}
    if "HOLD" in signals:
        return {"verdict": "REJECT", "conviction": conviction, "risk": 8, "reason": "Sideways"}
    verdict = "APPROVE" if conviction >= config.AI_MIN_CONVICTION else "REJECT"
    return {"verdict": verdict, "conviction": conviction, "risk": risk, "reason": "Local analysis"}
