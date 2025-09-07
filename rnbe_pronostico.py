#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RNBE – Generador de pronóstico (GitHub Actions)
- Meteo: Open-Meteo (GFS + ICON) para Belén de Escobar
- Salidas: WhatsApp (compacta) + Técnica (ambas con emojis)
- Orden: PRIMERO clima/temperatura/viento; LUEGO nivel del río
- Niveles del río San Fernando (06–20 h): desde niveles_san_fernando.json (si existe)
"""
import json, os, requests
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta, date

HERE = os.path.dirname(os.path.abspath(__file__))

def load_config():
    with open(os.path.join(HERE, "config.json"), "r", encoding="utf-8") as f:
        return json.load(f)

def load_levels():
    p = os.path.join(HERE, "niveles_san_fernando.json")
    if not os.path.exists(p):
        return {}
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)

def ensure_dir(p: str):
    os.makedirs(p, exist_ok=True)

def next_weekend(base: date) -> Tuple[date, date]:
    dow = base.weekday()  # lunes=0
    days_until_sat = (5 - dow) % 7
    sat = base + timedelta(days=days_until_sat)
    sun = sat + timedelta(days=1)
    return sat, sun

def fetch_open_meteo(lat: float, lon: float, tz: str, start: date, end: date, model: str) -> Dict:
    base = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": lat, "longitude": lon, "timezone": tz, "models": model,
        "hourly": ",".join([
            "temperature_2m","wind_speed_10m","wind_gusts_10m",
            "wind_direction_10m","precipitation_probability"
        ]),
        "windspeed_unit": "kmh",
        "start_date": start.isoformat(),
        "end_date": end.isoformat()
    }
    r = requests.get(base, params=params, timeout=40)
    r.raise_for_status()
    return r.json()

def circular_mean_deg(degs: List[float]) -> float:
    import math
    rad = [math.radians(d) for d in degs]
    sin_sum = sum(math.sin(x) for x in rad)
    cos_sum = sum(math.cos(x) for x in rad)
    return (math.degrees(math.atan2(sin_sum, cos_sum)) + 360.0) % 360.0

COMPASS_16 = ["N","NNE","NE","ENE","E","ESE","SE","SSE","S","SSO","SO","OSO","O","ONO","NO","NNO"]
def deg_to_compass_es(deg: float) -> str:
    ix = int((deg/22.5)+0.5) % 16
    return COMPASS_16[ix]

@dataclass
class SlotStats:
    speed_avg: float
    gust_max: float
    dir_avg_deg: float
    dir_avg_txt: str

def window_idx(times: List[str], h0: int, h1: int) -> List[int]:
    idx = []
    for i, t in enumerate(times):
        hh = int(t[11:13])
        if h0 <= hh < h1:
            idx.append(i)
    return idx

def stats_for_window(h: Dict, h0: int, h1: int) -> SlotStats:
    idx = window_idx(h["time"], h0, h1)
    if not idx:
        return SlotStats(0,0,0,"")
    speeds = [h["wind_speed_10m"][i] for i in idx if h["wind_speed_10m"][i] is not None]
    gusts  = [h["wind_gusts_10m"][i] for i in idx if h["wind_gusts_10m"][i] is not None]
    dirs   = [h["wind_direction_10m"][i] for i in idx if h["wind_direction_10m"][i] is not None]
    s_avg = sum(speeds)/len(speeds) if speeds else 0
    g_max = max(gusts) if gusts else 0
    d_avg = circular_mean_deg(dirs) if dirs else 0
    return SlotStats(s_avg, g_max, d_avg, deg_to_compass_es(d_avg) if dirs else "")

def aggregate_models(models_data: List[Dict]) -> Dict:
    base = models_data[0]["hourly"]
    times = base["time"]
    fields = ["temperature_2m","wind_speed_10m","wind_gusts_10m","wind_direction_10m","precipitation_probability"]
    agg = {f: [] for f in fields}
    for i in range(len(times)):
        for f in fields:
            vals = []
            for m in models_data:
                v = m["hourly"][f][i]
                if v is not None:
                    vals.append(v)
            if f == "wind_direction_10m":
                agg[f].append(circular_mean_deg(vals) if vals else None)
            else:
                agg[f].append(sum(vals)/len(vals) if vals else None)
    return {"time": times, **agg}

def day_slice(hourly: Dict, d: date) -> Dict:
    start = f"{d.isoformat()}T00:00"
    end   = f"{d.isoformat()}T23:59"
    out = {"time": [], "temperature_2m": [], "wind_speed_10m": [], "wind_gusts_10m": [], "wind_direction_10m": [], "precipitation_probability": []}
    for i,t in enumerate(hourly["time"]):
        if start <= t <= end:
            out["time"].append(t)
            for k in out.keys():
                if k == "time": continue
                out[k].append(hourly[k][i])
    return out

def get_slots(h: Dict, breve: bool):
    if breve:
        return {"manana": stats_for_window(h,6,12), "tarde": stats_for_window(h,12,20)}
    else:
        return {"manana": stats_for_window(h,6,11), "mediodia": stats_for_window(h,11,14), "tarde": stats_for_window(h,14,20)}

def semaforo(h: Dict, thr: Dict) -> str:
    slots = get_slots(h, breve=True)
    sust_max = max(s.speed_avg for s in slots.values())
    gust_max = max(s.gust_max for s in slots.values())
    prob = max([p for p in h.get("precipitation_probability",[]) if p is not None] or [0])
    if sust_max <= thr["green_max_sust"] and gust_max <= thr["green_max_gust"] and prob < 50:
        return "🟢"
    if sust_max <= thr["yellow_max_sust"] and gust_max <= thr["yellow_max_gust"] and prob < 70:
        return "🟡"
    return "🔴"

def temp_range(h: Dict) -> str:
    vals = [v for v in h["temperature_2m"] if v is not None]
    return f"{min(vals):.0f}–{max(vals):.0f} °C" if vals else "__–__ °C"

def precip_text(h: Dict) -> str:
    probs = [p for p in h["precipitation_probability"] if p is not None]
    if not probs: return ""
    pmax = max(probs)
    if pmax >= 60: return "Probables lluvias/chaparrones"
    if pmax >= 30: return "Alguna chance de chaparrones"
    return "Sin lluvias relevantes"

def r0(x: float) -> int:
    return int(round(x))

def round1(x: float) -> float:
    return float(f"{x:.1f}")

# ---- NUEVO ORDEN: CLIMA PRIMERO, RÍO DESPUÉS ----
def fmt_whatsapp(day_name: str, sem: str, temp: str, slots, lluvia: str, river: Optional[Dict]) -> str:
    lines = []
    lines.append(f"🗓️ {day_name}")
    lines.append(f"{sem}")
    lines.append(f"🌡️ {temp}")
    if lluvia:
        lines.append(f"☁️ {lluvia}")
    lines.append("")
    lines.append(f"💨 Mañana: {r0(slots['manana'].speed_avg)} km/h (ráf. {r0(slots['manana'].gust_max)}) {slots['manana'].dir_avg_txt}")
    if 'mediodia' in slots:
        lines.append(f"💨 Mediodía: {r0(slots['mediodia'].speed_avg)} km/h (ráf. {r0(slots['mediodia'].gust_max)}) {slots['mediodia'].dir_avg_txt} → {slots['manana'].dir_avg_txt}→{slots['mediodia'].dir_avg_txt}")
    lines.append(f"💨 Tarde: {r0(slots['tarde'].speed_avg)} km/h (ráf. {r0(slots['tarde'].gust_max)}) {slots['tarde'].dir_avg_txt} → {slots.get('mediodia', slots['manana']).dir_avg_txt}→{slots['tarde'].dir_avg_txt}")
    lines.append("")
    if 'mediodia' in slots:
        lines.append(f"🌀 Rotación: {slots['manana'].dir_avg_txt} → {slots['mediodia'].dir_avg_txt} → {slots['tarde'].dir_avg_txt}")
    else:
        lines.append(f"🌀 Rotación: {slots['manana'].dir_avg_txt} → {slots['tarde'].dir_avg_txt}")
    lines.append("")
    lines.append("🌊 Nivel del río (San Fernando 06–20 h):")
    if river:
        lines.append(f"🔻 {river['min']} m ({river['t_min']}) / 🔺 {river['max']} m ({river['t_max']})")
    else:
        lines.append("🔻 __ m (__:__) / 🔺 __ m (__:__)")
    return "\n".join(lines)

def fmt_tecnico(day_name: str, sem: str, temp: str, cond: str, slots, river: Optional[Dict]) -> str:
    L = []
    L += [f"### 🗓️ **{day_name}**", f"{sem}", ""]
    L += [f"🌡️ **Temperatura:** {temp}"]
    L += [f"☁️ **Condiciones:** {cond or '—'}", ""]
    L += ["💨 **Viento – tabla horaria**","| Franja | Vel. (km/h) | Ráf. (km/h) | Dirección | Rotación |","|--------|-------------:|------------:|-----------|----------|"]
    if 'mediodia' in slots:
        L += [f"| 🌅 Mañana | {round1(slots['manana'].speed_avg)} | {round1(slots['manana'].gust_max)} | {slots['manana'].dir_avg_txt} | — |"]
        L += [f"| ☀️ Mediodía | {round1(slots['mediodia'].speed_avg)} | {round1(slots['mediodia'].gust_max)} | {slots['mediodia'].dir_avg_txt} | {slots['manana'].dir_avg_txt} → {slots['mediodia'].dir_avg_txt} |"]
        L += [f"| 🌇 Tarde | {round1(slots['tarde'].speed_avg)} | {round1(slots['tarde'].gust_max)} | {slots['tarde'].dir_avg_txt} | {slots['mediodia'].dir_avg_txt} → {slots['tarde'].dir_avg_txt} |",""]
        L += ["🌀 **Rosa de vientos – texto**", f"{slots['manana'].dir_avg_txt} → {slots['mediodia'].dir_avg_txt} → {slots['tarde'].dir_avg_txt}", ""]
    else:
        L += [f"| 🌅 Mañana | {round1(slots['manana'].speed_avg)} | {round1(slots['manana'].gust_max)} | {slots['manana'].dir_avg_txt} | — |"]
        L += [f"| 🌇 Tarde | {round1(slots['tarde'].speed_avg)} | {round1(slots['tarde'].gust_max)} | {slots['tarde'].dir_avg_txt} | {slots['manana'].dir_avg_txt} → {slots['tarde'].dir_avg_txt} |",""]
        L += ["🌀 **Rosa de vientos – texto**", f"{slots['manana'].dir_avg_txt} → {slots['tarde'].dir_avg_txt}", ""]
    # Nota técnica simple
    gust_max = max(slots['manana'].gust_max, slots.get('mediodia', slots['manana']).gust_max, slots['tarde'].gust_max)
    if any(d in ['SE','SSE'] for d in [slots['manana'].dir_avg_txt, slots.get('mediodia', slots['manana']).dir_avg_txt, slots['tarde'].dir_avg_txt]) and gust_max >= 30:
        nota = "⚠️ Posible sudestada por la tarde (SE) con aumento del nivel y deriva."
    else:
        nota = "📝 Rotación y ráfagas dentro de parámetros habituales."
    L += [f"**Nota técnica:** {nota}",""]
    # Río al final
    L += ["🌊 **Nivel del río – San Fernando (06–20 h):**"]
    if river:
        L += ["| Hora | Nivel (m) |","|------|-----------|", f"| ⏰ {river['t_min']} | 🔻 {river['min']} (mínima) |", f"| ⏰ {river['t_max']} | 🔺 {river['max']} (máxima) |",""]
    else:
        L += ["_Sin datos de río cargados (use niveles_san_fernando.json)._",""]
    return "\n".join(L)

def main():
    cfg = load_config()
    levels = load_levels()
    tz = cfg["timezone"]

    # Fecha base = UTC hoy → próximo finde
    today = datetime.utcnow().date()
    sab, dom = next_weekend(today)

    # Feriado lunes?
    feriado = None
    monday = sab + timedelta(days=2)
    if monday.isoformat() in cfg.get("feriados", []):
        feriado = monday

    # Meteo GFS/ICON
    models = []
    for m in cfg["models"]:
        models.append(fetch_open_meteo(cfg["lat"], cfg["lon"], tz, sab, feriado or dom, m))
    hourly = aggregate_models(models)

    def get_day(d: date):
        h = day_slice(hourly, d)
        sem = semaforo(h, cfg["semaforo_thresholds"])
        temp = temp_range(h)
        cond = precip_text(h)
        slots_breve = get_slots(h, breve=True)
        slots_tec   = get_slots(h, breve=False)
        river = levels.get(d.isoformat())
        return {"h":h,"sem":sem,"temp":temp,"cond":cond,"sb":slots_breve,"st":slots_tec,"river":river}

    ds = {"sab": get_day(sab), "dom": get_day(dom)}
    if feriado:
        ds["fer"] = get_day(feriado)

    outdir = os.path.join(HERE, "out")
    ensure_dir(outdir)
    tag = sab.strftime("%Y%m%d")

    # WhatsApp
    w = []
    w.append("Queridas socias y socios:\nLes compartimos el pronóstico para este fin de semana:\n")
    w.append(fmt_whatsapp(f"Sábado {sab.day}", ds['sab']["sem"], ds['sab']["temp"], ds['sab']["st"], ds['sab']["cond"], ds['sab']["river"]))
    w.append("---")
    w.append(fmt_whatsapp(f"Domingo {dom.day}", ds['dom']["sem"], ds['dom']["temp"], ds['dom']["st"], ds['dom']["cond"], ds['dom']["river"]))
    if feriado:
        w.append("---")
        w.append(fmt_whatsapp(f"Lunes {feriado.day}", ds['fer']["sem"], ds['fer']["temp"], ds['fer']["st"], ds['fer']["cond"], ds['fer']["river"]))
    w.append("\nNos vemos en el club 🛶")
    with open(os.path.join(outdir, f"whatsapp_{tag}.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(w))

    # Técnico
    t = []
    t.append("Estimadas socias y socios:\n**Cobertura:** Sábado y Domingo" + (f" y Lunes {feriado.day}" if feriado else "") + "\n**Zona:** Delta – centro en Belén de Escobar\n")
    t.append("---\n")
    t.append(fmt_tecnico(f"Sábado {sab.day}", ds["sab"]["sem"], ds["sab"]["temp"], ds["sab"]["cond"], ds["sab"]["st"], ds["sab"]["river"]))
    t.append("---\n")
    t.append(fmt_tecnico(f"Domingo {dom.day}", ds["dom"]["sem"], ds["dom"]["temp"], ds["dom"]["cond"], ds["dom"]["st"], ds["dom"]["river"]))
    if feriado:
        t.append("---\n")
        t.append(fmt_tecnico(f"Lunes {feriado.day}", ds["fer"]["sem"], ds["fer"]["temp"], ds["fer"]["cond"], ds["fer"]["st"], ds["fer"]["river"]))
    t.append("\nNos encontramos en el club para compartir la experiencia.\nCRNBE")
    with open(os.path.join(outdir, f"tecnico_{tag}.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(t))

    print("OK – archivos creados en out/")

if __name__ == "__main__":
    main()
