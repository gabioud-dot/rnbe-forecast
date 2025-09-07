# -*- coding: utf-8 -*-
"""
Envia por Gmail los archivos generados (WhatsApp + Técnico).

Lee remitente/destinatarios/asunto desde variables de entorno:
- EMAIL_FROM (obligatoria, tu cuenta Gmail remitente)
- EMAIL_TO   (obligatoria, lista separada por comas)
- SUBJECT_PREFIX (opcional, por defecto "Pronóstico RNBE – fin de semana")
Y usa el App Password desde:
- GMAIL_APP_PASSWORD (SECRET de GitHub Actions o variable local)

Requiere: pip install yagmail
"""
import os, datetime as dt
from pathlib import Path
import yagmail

EMAIL_FROM = os.environ.get("EMAIL_FROM")
EMAIL_TO = os.environ.get("EMAIL_TO")
SUBJECT_PREFIX = os.environ.get("SUBJECT_PREFIX", "Pronóstico RNBE – fin de semana")

if not EMAIL_FROM or not EMAIL_TO:
    raise RuntimeError("Faltan variables EMAIL_FROM y/o EMAIL_TO. Configurarlas como Variables en GitHub Actions.")

DESTINATARIOS = [e.strip() for e in EMAIL_TO.split(",") if e.strip()]

BASE_DIR = Path(__file__).resolve().parent
OUT_DIR = BASE_DIR / "out"

# Determinar próximo sábado (coincide con nombres de archivo)
hoy = dt.date.today()
sabado = hoy + dt.timedelta((5 - hoy.weekday()) % 7)  # 5 = sábado
tag = sabado.strftime("%Y%m%d")

whatsapp = OUT_DIR / f"whatsapp_{tag}.txt"
tecnico  = OUT_DIR / f"tecnico_{tag}.txt"

subject = f"{SUBJECT_PREFIX} {sabado.strftime('%d/%m/%Y')}"
body = "Adjuntamos los pronósticos del fin de semana (WhatsApp + técnico)."

app_password = os.environ.get("GMAIL_APP_PASSWORD")
if not app_password:
    raise RuntimeError("Falta GMAIL_APP_PASSWORD en el entorno (secret de Actions o variable local).")

yag = yagmail.SMTP(user=EMAIL_FROM, password=app_password)

attachments = []
if whatsapp.exists():
    attachments.append(str(whatsapp))
if tecnico.exists():
    attachments.append(str(tecnico))

if not attachments:
    body += "\n\n⚠️ No se encontraron archivos en 'out/'. Verificá la ejecución previa."

yag.send(to=DESTINATARIOS, subject=subject, contents=body, attachments=attachments or None)
print("Correo enviado:", subject, "a", DESTINATARIOS)
