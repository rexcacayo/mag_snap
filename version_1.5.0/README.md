# MagSnap 3D

Complemento de Blender (4.2 a 5.x) para **partir figuras y modelos en piezas imprimibles** y unirlas con
**imanes, espigas o un eje de giro**. Todo en modo Objeto. Licencia GPL-3.0.

## Qué hace

- **Línea de corte dibujada**: pinchas alrededor de la pieza y la línea va pegada a la superficie.
- **Corte curvo** que sigue la línea por dentro de la pieza: la junta queda escondida en pliegues
  (barbilla, axila, borde de un músculo). Vista previa en verde de la cara del corte.
- **Corte recto** por el plano medio de la línea, si lo prefieres.
- Solo corta lo que rodea la línea: el resto del modelo no se toca.
- **Conectores**:
  - **Imán**: alojamiento enfrentado en las dos caras, con holgura FDM.
  - **Espiga**: agujeros en las dos caras y la espiga suelta para imprimir.
  - **Giro**: eje a presión que deja girar la pieza (cabeza, torreta, rueda).
  - Dos por zona si caben (no gira) y con pared mínima comprobada.
- **Exportar STL** en mm de todas las piezas.
- El original nunca se modifica: queda oculto.

## Instalar

Editar → Preferencias → Complementos → Instalar desde disco → `mag_snap_3d-1.5.0.zip`.
Vista 3D → tecla **N** → pestaña **MagSnap 3D**.

Guía de uso completa en `mag_snap_3d/LEEME.md`.

## Licencia

GPL-3.0-or-later (ver [LICENSE](LICENSE)). Gratis para usar, modificar y compartir; si redistribuyes una versión modificada, publica también su código. Es la licencia que exige extensions.blender.org.
