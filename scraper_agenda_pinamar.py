"""
Scraper de eventos - Agenda Pinamar (https://agenda.pinamar.gob.ar/)

Extrae: imagen, título, fecha, horario, descripción corta y descripción
COMPLETA (entrando a la página propia de cada evento, ej:
https://agenda.pinamar.gob.ar/copa-humming-airways/) de cada evento.

Recorre automáticamente todas las páginas de resultados (detecta el número de
página más alto en los links y las descarga todas, sin depender de un botón
"Siguiente" que puede tener íconos y romper la detección por texto).

Las imágenes se descargan y se guardan localmente en la carpeta "imagenes/"
para evitar el error "hotlinked" que tira el sitio cuando se muestran sus
imágenes embebidas desde otro dominio (localhost, GitHub Pages, etc.).

Requisitos:
    pip install requests beautifulsoup4

Uso:
    python scraper_agenda_pinamar.py
    -> Genera "eventos_pinamar.json", "eventos_pinamar.csv" y la carpeta "imagenes/"

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
CARPETA_IMAGENES = os.path.join(CARPETA_SCRIPT, "imagenes")

BASE_URL = "https://agenda.pinamar.gob.ar/"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    # Muchos sitios bloquean la carga de imágenes si el pedido no "parece"
    # venir del propio sitio (protección anti-hotlinking). Al descargar
    # nosotros mismos la imagen con este Referer, la conseguimos sin problema
    # y listo: queda guardada localmente para siempre.
    "Referer": BASE_URL,
}


def obtener_html(url):
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    resp.encoding = "utf-8"
    return resp.text


def obtener_slug(url_evento):
    """Extrae la parte final de la URL del evento, ej:
    'https://agenda.pinamar.gob.ar/copa-humming-airways/' -> 'copa-humming-airways'
    """
    partes = [p for p in url_evento.split("/") if p]
    return partes[-1] if partes else "evento"


def descargar_imagen(url_imagen, slug):
    """
    Descarga una imagen a la carpeta 'imagenes/' y devuelve la ruta
    relativa (ej: 'imagenes/copa-humming-airways.jpeg') para usar en el
    JSON/HTML. Usa el slug del evento (no la posición en la lista) como
    nombre de archivo, para que sea siempre el mismo de una corrida a otra
    y así se pueda limpiar con precisión lo que ya no corresponde.
    Si falla la descarga, devuelve la URL original como respaldo.
    """
    if not url_imagen:
        return ""

    os.makedirs(CARPETA_IMAGENES, exist_ok=True)

    extension = os.path.splitext(url_imagen.split("?")[0])[1] or ".jpg"
    extension = re.sub(r"[^A-Za-z0-9.]", "", extension) or ".jpg"
    nombre_archivo = f"{slug}{extension}"
    ruta_local = os.path.join(CARPETA_IMAGENES, nombre_archivo)
    ruta_relativa = f"imagenes/{nombre_archivo}"

    # Si ya la descargamos antes (corrida anterior), no la pedimos de nuevo
    if os.path.exists(ruta_local):
        return ruta_relativa

    try:
        resp = requests.get(url_imagen, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        with open(ruta_local, "wb") as f:
            f.write(resp.content)
        return ruta_relativa
    except Exception as e:
        print(f"  ! No se pudo descargar la imagen {url_imagen}: {e}")
        return url_imagen  # respaldo: al menos queda el link original


def limpiar_imagenes_huerfanas(nombres_usados):
    """
    Borra de la carpeta 'imagenes/' cualquier archivo que no corresponda
    a ningún evento de la corrida actual (eventos viejos, vencidos, o que
    ya no están publicados en el sitio).
    """
    if not os.path.isdir(CARPETA_IMAGENES):
        return

    borrados = 0
    for nombre_archivo in os.listdir(CARPETA_IMAGENES):
        if nombre_archivo not in nombres_usados:
            os.remove(os.path.join(CARPETA_IMAGENES, nombre_archivo))
            borrados += 1

    if borrados:
        print(f"  {borrados} imagen(es) vieja(s) eliminada(s) (ya no corresponden a ningún evento actual)")


# Estos títulos son de un widget fijo ("Actividades permanentes") que WordPress
# repite al pie de TODAS las páginas del sitio. Sirven para saber dónde termina
# la descripción real del evento y dónde empieza ese contenido repetido.
BOILERPLATE_STOP = {
    "CENTROS DE ATENCIÓN AL TURISTA",
    "FERIAS, PASEOS Y EXPOSICIONES",
    "RECREACIÓN",
    "AVENTURA Y DIVERSIÓN",
    "DEPORTE",
    "CASAS DE ARTISTAS",
    "ESPACIOS CULTURALES",
    "ACTIVIDADES PERMANENTES",
    "VOLVER ARRIBA",
    "MENÚ",
}


def obtener_detalle_evento(url_evento, titulo):
    """
    Entra a la página propia del evento (ej: .../copa-humming-airways/)
    y extrae el texto completo de la descripción (modalidad, horarios,
    teléfonos de inscripción, etc. — todo lo que está debajo del título).

    Cómo lo hace: el título del evento aparece dos veces en la página
    (una como encabezado, y otra repetida justo antes del texto libre de
    descripción). Tomamos todo el texto que viene después de la ÚLTIMA
    aparición del título, y cortamos apenas aparece el widget fijo de
    "Actividades permanentes" que se repite en todas las páginas del sitio.
    """
    try:
        html = obtener_html(url_evento)
    except Exception as e:
        print(f"  ! No se pudo obtener el detalle de {url_evento}: {e}")
        return ""

    soup = BeautifulSoup(html, "html.parser")
    textos = [limpiar(t) for t in soup.stripped_strings if limpiar(t)]

    titulo_upper = titulo.strip().upper()
    indices_titulo = [i for i, t in enumerate(textos) if t.upper() == titulo_upper]

    if not indices_titulo:
        return ""

    inicio = indices_titulo[-1] + 1  # texto después de la última mención del título

    lineas = []
    for t in textos[inicio:]:
        if t.upper() in BOILERPLATE_STOP:
            break
        lineas.append(t)
        if len(lineas) >= 25:  # límite de seguridad por si algo no corta bien
            break

    return limpiar(" ".join(lineas))


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


def obtener_max_pagina(html):
    """
    Busca en TODOS los links de la página (no solo el botón "Siguiente")
    el número de página más alto que aparezca en URLs del tipo:
        https://agenda.pinamar.gob.ar/page/2/
    Esto es más confiable que buscar el texto "Siguiente", porque ese
    botón a veces trae un ícono adentro (flecha) y el texto solo no
    alcanza para detectarlo.
    """
    soup = BeautifulSoup(html, "html.parser")
    max_pagina = 1
    for a in soup.find_all("a", href=True):
        m = re.search(r"/page/(\d+)/?", a["href"])
        if m:
            max_pagina = max(max_pagina, int(m.group(1)))
    return max_pagina


def main():
    todos_los_eventos = []

    # Primero descargamos la página 1 para saber cuántas páginas hay en total
    print(f"Descargando página 1: {BASE_URL}")
    html = obtener_html(BASE_URL)
    eventos = parsear_pagina(html)
    print(f"  -> {len(eventos)} eventos encontrados")
    todos_los_eventos.extend(eventos)

    total_paginas = obtener_max_pagina(html)
    print(f"Total de páginas detectadas: {total_paginas}")

    for pagina_num in range(2, total_paginas + 1):
        url_actual = f"{BASE_URL}page/{pagina_num}/"
        time.sleep(1)  # ser respetuoso con el servidor
        print(f"Descargando página {pagina_num}: {url_actual}")
        html = obtener_html(url_actual)
        eventos = parsear_pagina(html)
        print(f"  -> {len(eventos)} eventos encontrados")
        todos_los_eventos.extend(eventos)

    # Descargar todas las imágenes localmente (evita el bloqueo "hotlinked"
    # que da el sitio cuando se muestran sus imágenes desde otro dominio)
    print("\nDescargando imágenes...")
    nombres_usados = set()
    for ev in todos_los_eventos:
        slug = obtener_slug(ev["url_evento"])
        ev["imagen"] = descargar_imagen(ev["imagen"], slug)
        if ev["imagen"].startswith("imagenes/"):
            nombres_usados.add(ev["imagen"].split("imagenes/", 1)[1])
    print(f"Imágenes guardadas en: {CARPETA_IMAGENES}")

    # Limpiar imágenes de corridas anteriores que ya no corresponden
    # a ningún evento de esta corrida (evita que se acumulen archivos viejos)
    limpiar_imagenes_huerfanas(nombres_usados)

    # Entrar a la página propia de cada evento para traer la descripción completa
    print("\nBuscando descripción completa de cada evento...")
    for i, ev in enumerate(todos_los_eventos, start=1):
        print(f"  ({i}/{len(todos_los_eventos)}) {ev['titulo']}")
        ev["detalle"] = obtener_detalle_evento(ev["url_evento"], ev["titulo"])
        time.sleep(0.5)  # ser respetuoso con el servidor

    # Guardar JSON
    with open(RUTA_JSON, "w", encoding="utf-8") as f:
        json.dump(todos_los_eventos, f, ensure_ascii=False, indent=2)

    # Guardar CSV
    with open(RUTA_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f, fieldnames=["titulo", "fecha", "horario", "imagen", "descripcion", "detalle", "url_evento"]
        )
        writer.writeheader()
        writer.writerows(todos_los_eventos)

    print(f"\nTotal de eventos extraídos: {len(todos_los_eventos)}")
    print(f"Archivos generados:\n  {RUTA_JSON}\n  {RUTA_CSV}")


if __name__ == "__main__":
    main()
