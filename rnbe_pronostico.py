#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# rnbe_pronostico.py (orden modificado: clima primero, nivel del río al final)

def fmt_whatsapp(day_name, sem, temp, slots, lluvia, river):
    lines = []
    lines.append(f"🗓️ {day_name}")
    lines.append(f"{sem}")
    lines.append(f"🌡️ {temp}")
    if lluvia:
        lines.append(f"☁️ {lluvia}")
    lines.append("")
    lines.append("💨 Mañana: ...")
    lines.append("💨 Mediodía: ...")
    lines.append("💨 Tarde: ...")
    lines.append("")
    lines.append("🌀 Rotación: ...")
    lines.append("")
    lines.append("🌊 Nivel del río (San Fernando 06–20 h):")
    if river:
        lines.append(f"🔻 {river['min']} m ({river['t_min']}) / 🔺 {river['max']} m ({river['t_max']})")
    else:
        lines.append("🔻 __ m (__:__) / 🔺 __ m (__:__)")
    return "\n".join(lines)

def fmt_tecnico(day_name, sem, temp, cond, slots, river):
    L = []
    L += [f"### 🗓️ **{day_name}**", f"{sem}", ""]
    L += [f"🌡️ **Temperatura:** {temp}", f"☁️ **Condiciones:** {cond or '—'}", ""]
    L += ["💨 **Viento – tabla horaria**", "... tabla ...", ""]
    L += ["🌀 **Rosa de vientos – texto**", "... rotación ...", ""]
    L += ["**Nota técnica:** ...", ""]
    L += ["🌊 **Nivel del río – San Fernando (06–20 h):**"]
    if river:
        L += [f"| ⏰ {river['t_min']} | 🔻 {river['min']} (mínima) |",
              f"| ⏰ {river['t_max']} | 🔺 {river['max']} (máxima) |",""]
    else:
        L += ["_Sin datos de río cargados._",""]
    return "\n".join(L)
