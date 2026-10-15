# MagSnap 3D 1.6.0

Complemento clásico para Blender 4.2 a 5.x (probado en 5.2.1 LTS). Sin dependencias externas.

## Regla de la casa: todo en modo Objeto

Todos los botones trabajan en modo Objeto y ninguno cambia de modo por su cuenta. Si estás en Edición, el panel lo avisa y tiene un botón para volver.

## Instalar

1. Desactiva la versión anterior en Editar > Preferencias > Complementos y reinicia Blender.
2. Instalar desde disco → `dist/mag_snap_3d-1.6.0.zip` (sin descomprimir).
3. Vista 3D → tecla N → pestaña **MagSnap 3D**.

## Uso: escoger y listo

El panel va en cuatro pasos:

1. **Modelo**: selecciona la malla. El panel muestra su nombre, medidas en mm y la unidad detectada
   (Automático reconoce STL en mm, cm o m por su tamaño; se puede forzar a mano).
2. **Conector**: Imán, Espiga o Ninguno, con sus medidas en mm. «Cantidad Automático» pone dos por
   zona del corte si caben (así la pieza no gira) y si no, uno. En «Ajustes finos»: holgura y pared mínima.
3. **Cortar**: elige **Curvo** (lo normal) o **Recto**. «Dibujar línea» y pincha alrededor de la pieza
   por donde quieres separarla: la línea va **pegada a la superficie** entre clic y clic. Cierra con
   clic en el punto verde o Intro; Retroceso quita el último punto, Esc cancela. La rueda y el botón
   central siguen haciendo zoom y girando la vista. Al cerrar se ve **en verde la cara del corte**.
   Después, «Separar por la línea».
   - **Curvo**: el corte sigue la línea por dentro de la pieza. Llévala por pliegues naturales
     (debajo de la barba, la axila, el borde de un músculo, la manga) y la junta casi no se verá.
   - **Recto**: cara plana, por el plano medio de la línea.
   - **Desde la vista** (lo más fácil para partir por la mitad, separar patas o la cabeza): mira la
     pieza de frente, pincha de un lado a otro **sin girar la vista** y pulsa Intro. Corta recto
     hacia el fondo siguiendo tu trazo, como un cuchillo. Los extremos se alargan solos hasta salir
     de la pieza. Con Giro, pincha solo 2 puntos (línea recta).
   - En los dos casos **solo se corta dentro de la línea**: el resto del modelo no se toca aunque
     esté en la misma dirección (cortar un brazo no corta el cuerpo).
4. **Exportar STL** en mm, de las piezas seleccionadas o visibles. Si el .blend no está guardado, la
   carpeta relativa `//` va a Documentos (el panel lo indica).

Las piezas salen como `<modelo>_01` (la grande) y `<modelo>_02` (la que se separa). El original queda oculto.

## Cómo coloca los conectores

- El corte puede tener varias zonas (p. ej. cuello y brazo): se ponen conectores en cada zona donde quepan.
- Solo se usan puntos con la pared mínima alrededor **y** material suficiente a los dos lados del corte.
- Si no cabe ninguno, el mensaje dice el diámetro máximo que admite ese corte.

## Qué cambia respecto a 1.5

- Corte **Desde la vista**: no hace falta rodear la pieza ni girar la vista mientras pinchas.

## Qué cambió respecto a 1.4

- **Corte curvo** que sigue la línea (como en ZBrush/Meshmixer): la cara del corte es una superficie
  tendida sobre la línea. Con vista previa en verde antes de cortar.
- La línea se dibuja **pegada a la superficie** entre los clics.
- El corte (curvo o recto) **solo afecta a lo que rodea la línea**. Antes el plano cortaba todo el
  modelo por donde pasaba.
- Imanes y espigas van **perpendiculares a la cara del corte** en cada punto.
- **Giro** siempre hace el corte recto (una cara curva no deja girar). La pieza que gira es la pequeña.
- Las piezas quedan separadas por una holgura de 0,05 mm.

## Qué cambió respecto a 1.3

- Línea de corte dibujada en lugar del plano (clic sobre el modelo, como en BigPrint).
- Conector **Giro**: un eje sale de la pieza de abajo y entra a presión en la de arriba, que gira sobre
  él sin salirse (reborde + ranura en la punta). En ejes de menos de Ø4 mm, solo fricción.
- La rueda del ratón y el botón central ya no se bloquean mientras eliges dónde cortar.

## Qué cambió respecto a 1.2

- Unidades automáticas (antes «Escala de la escena» trataba un STL en mm como metros y calculaba imanes de micras).
- Los imanes ya no van a los bordes de la sección: se descartan los puntos sin material detrás.
- Si no caben dos, pone uno en lugar de fallar. Un conector por cada zona del corte.
- Panel nuevo en 4 pasos, con espigas además de imanes.
- El plano de corte usado se borra para que no se reutilice por error.
- «Caras marcadas» sale del panel (el código sigue en `common.split_marked`).

## Límites

- El modelo debe ser una malla cerrada (manifold). Si no lo es, repáralo antes (por ejemplo en 3D LAB).
- Vista desde el corte, la línea no puede cruzarse consigo misma (si pasa, el plugin lo avisa).
- Si la cara curva sale de la pieza y vuelve a entrar (zonas muy cóncavas), también corta ahí:
  mira la vista previa en verde antes de separar.
- Imprime una muestra para ajustar holguras a tu impresora y material.
