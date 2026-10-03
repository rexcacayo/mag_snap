# MagSnap 3D 1.3.0

Complemento clásico para Blender 4.2 a 5.x (probado en 5.2.1 LTS). Sin dependencias externas.

## Regla de la casa: todo en modo Objeto

Todos los botones trabajan en modo Objeto y ninguno cambia de modo por su cuenta. Si estás en Edición, el panel lo avisa y tiene un botón para volver.

## Instalar

1. Desactiva la versión anterior en Editar > Preferencias > Complementos y reinicia Blender.
2. Instalar desde disco → `dist/mag_snap_3d-1.3.0.zip` (sin descomprimir).
3. Vista 3D → tecla N → pestaña **MagSnap 3D**.

## Uso: escoger y listo

El panel va en cuatro pasos:

1. **Modelo**: selecciona la malla. El panel muestra su nombre, medidas en mm y la unidad detectada
   (Automático reconoce STL en mm, cm o m por su tamaño; se puede forzar a mano).
2. **Conector**: Imán, Espiga o Ninguno, con sus medidas en mm. «Cantidad Automático» pone dos por
   zona del corte si caben (así la pieza no gira) y si no, uno. En «Ajustes finos»: holgura y pared mínima.
3. **Cortar**: pulsa «Clic en el modelo para separar» y pasa el ratón por la pieza. X / Y / Z cambia la
   orientación, la rueda inclina de 5 en 5°, clic separa, Esc cancela.
   Si prefieres colocarlo tú: «Plano manual», muévelo (G / R) y «Separar».
4. **Exportar STL** en mm, de las piezas seleccionadas o visibles. Si el .blend no está guardado, la
   carpeta relativa `//` va a Documentos (el panel lo indica).

Las piezas salen como `<modelo>_01` (lado de abajo del plano) y `<modelo>_02`. El original queda oculto.

## Cómo coloca los conectores

- El corte puede tener varias zonas (p. ej. cuello y brazo): se ponen conectores en cada zona donde quepan.
- Solo se usan puntos con la pared mínima alrededor **y** material suficiente a los dos lados del corte.
- Si no cabe ninguno, el mensaje dice el diámetro máximo que admite ese corte.

## Qué cambia respecto a 1.2

- Unidades automáticas (antes «Escala de la escena» trataba un STL en mm como metros y calculaba imanes de micras).
- Los imanes ya no van a los bordes de la sección: se descartan los puntos sin material detrás.
- Si no caben dos, pone uno en lugar de fallar. Un conector por cada zona del corte.
- Panel nuevo en 4 pasos, con espigas además de imanes.
- El plano de corte usado se borra para que no se reutilice por error.
- «Caras marcadas» sale del panel (el código sigue en `common.split_marked`).

## Límites

- El modelo debe ser una malla cerrada (manifold). Si no lo es, repáralo antes (por ejemplo en 3D LAB).
- Imprime una muestra para ajustar holguras a tu impresora y material.
