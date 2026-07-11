"""
Scraper de eventos - Agenda Pinamar (https://agenda.pinamar.gob.ar/)

Extrae: imagen, título, fecha, horario y descripción (lugar/detalle) de cada evento.
Recorre automáticamente todas las páginas de resultados (paginación "Siguiente").

Requisitos:
    pip install requests beautifulsoup4

Uso:
    python scraper_agenda_pinamar.py
    -> Genera un archivo "eventos_pinamar.json" y "eventos_pinamar.csv"

NOTA IMPORTANTE:
Este script fue armado en base a la estructura típica de sitios WordPress con
grillas de eventos (imagen -> fecha -> título -> lugar -> horario -> precio).
Si al ejecutarlo ves que "titulo", "fecha", etc. salen vacíos, es porque el sitio
cambió sus clases CSS. Más abajo te explico cómo ajustarlo en 2 minutos usando
el Inspector del navegador (F12).
"""

import requests
from bs4 import BeautifulSoup
import json
import csv
import re
import time
import os

# Guarda los archivos siempre en la misma carpeta donde está este script
# (así quedan junto al index.html sin importar desde dónde lo ejecutes)
CARPETA_SCRIPT = os.path.dirname(os.path.abspath(__file__))
RUTA_JSON = os.path.join(CARPETA_SCRIPT, "eventos_pinamar.json")
RUTA_CSV = os.path.join(CARPETA_SCRIPT, "eventos_pinamar.csv")

BASE_URL = "https://agenda.pinamar.gob.ar/"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
}


def obtener_html(url):
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    resp.encoding = "utf-8"
    return resp.text


def limpiar(texto):
    if not texto:
        return ""
    return re.sub(r"\s+", " ", texto).strip()


def parsear_pagina(html):
    """
    Intenta detectar automáticamente cada 'tarjeta' de evento buscando
    los enlaces <a> que apuntan a una sub-página propia del evento
    (patrón: agenda.pinamar.gob.ar/nombre-del-evento/).
    A partir de cada enlace, sube al contenedor padre y extrae los datos
    cercanos (imagen, fecha, título, lugar, horario).
    """
    soup = BeautifulSoup(html, "html.parser")
    eventos = []

    # Cada evento tiene un <a> con imagen, y otro <a> con el título en un heading
    # (h5/h6). Buscamos los headings que contienen un link a una sub-url del sitio.
    posibles_titulos = soup.select("h1 a, h2 a, h3 a, h4 a, h5 a, h6 a")

    vistos = set()

    for link_titulo in posibles_titulos:
        href = link_titulo.get("href", "")
        if not href.startswith(BASE_URL) or href.rstrip("/") == BASE_URL.rstrip("/"):
            continue
        if href in vistos:
            continue
        vistos.add(href)

        titulo = limpiar(link_titulo.get_text())

        # Contenedor "tarjeta" del evento: subimos algunos niveles hasta encontrar
        # un bloque que también contenga la imagen del evento.
        contenedor = link_titulo
        imagen_url = None
        fecha = ""
        horario = ""
        descripcion_lineas = []

        for _ in range(6):
            if contenedor is None:
                break
            contenedor = contenedor.parent
            if contenedor is None:
                break

            img_tag = contenedor.find("img")
            if img_tag and not imagen_url:
                imagen_url = img_tag.get("src") or img_tag.get("data-src")

            texto_bloque = limpiar(contenedor.get_text(separator="|"))
            partes = [p.strip() for p in texto_bloque.split("|") if p.strip()]

            # La fecha suele tener formato "11 JUL" (día + mes abreviado)
            for parte in partes:
                if re.match(r"^\d{1,2}\s+[A-ZÁÉÍÓÚ]{3,4}$", parte.upper()):
                    fecha = parte.upper()
                if re.match(r"^\d{1,2}(:\d{2})?\s*hs$", parte, re.IGNORECASE) or \
                   "a confirmar" in parte.lower():
                    horario = parte

            if imagen_url and fecha:
                # Ya juntamos lo esencial, guardamos las demás líneas como descripción
                descripcion_lineas = [
                    p for p in partes
                    if p != titulo and p != fecha and p != horario
                ]
                break

        eventos.append({
            "titulo": titulo,
            "fecha": fecha,
            "horario": horario,
            "imagen": imagen_url or "",
            "descripcion": limpiar(" | ".join(descripcion_lineas)),
            "url_evento": href,
        })

    return eventos


def obtener_url_pagina_siguiente(html):
    soup = BeautifulSoup(html, "html.parser")
    link_siguiente = soup.find("a", string=re.compile("Siguiente", re.IGNORECASE))
    if link_siguiente and link_siguiente.get("href"):
        return link_siguiente["href"]
    return None


def main():
    todos_los_eventos = []
    url_actual = BASE_URL
    pagina_num = 1

    while url_actual:
        print(f"Descargando página {pagina_num}: {url_actual}")
        html = obtener_html(url_actual)
        eventos = parsear_pagina(html)
        print(f"  -> {len(eventos)} eventos encontrados")
        todos_los_eventos.extend(eventos)

        url_actual = obtener_url_pagina_siguiente(html)
        pagina_num += 1
        time.sleep(1)  # ser respetuoso con el servidor

    # Guardar JSON
    with open(RUTA_JSON, "w", encoding="utf-8") as f:
        json.dump(todos_los_eventos, f, ensure_ascii=False, indent=2)

    # Guardar CSV
    with open(RUTA_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f, fieldnames=["titulo", "fecha", "horario", "imagen", "descripcion", "url_evento"]
        )
        writer.writeheader()
        writer.writerows(todos_los_eventos)

    print(f"\nTotal de eventos extraídos: {len(todos_los_eventos)}")
    print(f"Archivos generados:\n  {RUTA_JSON}\n  {RUTA_CSV}")


if __name__ == "__main__":
    main()
