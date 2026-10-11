# Demostración (sin modelos y sin Internet)

`demo_windows.bat` (Windows) o `./demo_macos.sh` (Mac) — o `python -m podcleany demo`. Crea 2 episodios sintéticos con anuncios, arranca el sistema real (API + worker) en una carpeta aparte (`<datos>/demo`, no toca su biblioteca) y abre la interfaz. Siga los pasos que imprime la consola:

1. **Analizar** el episodio 1 → 3 tramos: la intro (falso anuncio a propósito), un anuncio detectado y un «posible anuncio».
2. **Conservar y proteger** la intro; **Quitar** el posible anuncio; **Generar audio sin anuncios**; **Descargar audio**. Al generar, el sistema aprende los anuncios que quitó.
3. Pegue el enlace del episodio 2 (lo muestra la consola) y analice: el anuncio sale como «Anuncio ya conocido» (reconocido por huella, sin transcribir) y la intro protegida ya no aparece.

Limitación: la voz es sintética y la «transcripción» es un guion (`podcleany/demo.py`); la demo muestra el flujo, las huellas y la interfaz, **no** la calidad de la IA real.
