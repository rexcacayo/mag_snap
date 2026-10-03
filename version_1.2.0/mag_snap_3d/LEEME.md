# MagSnap 3D 1.2.0

Complemento clásico para Blender 4.2 a 5.x (probado en 5.2.1 LTS). Sin dependencias externas.

## Regla de la casa: todo en modo Objeto

Todos los botones trabajan en modo Objeto y ninguno cambia de modo por su cuenta. Si estás en Edición, el panel lo avisa y tiene un botón para volver.

## Instalar

1. Desactiva la versión anterior en Editar > Preferencias > Complementos y reinicia Blender.
2. Instalar desde disco → `dist/mag_snap_3d-1.2.0.zip` (sin descomprimir).
3. Vista 3D → tecla N → pestaña **MagSnap 3D**.

## Lo rápido: elegir y clic

1. Selecciona el modelo (modo Objeto).
2. Pulsa **«Clic en el modelo para separar»** y pasa el ratón por la pieza: el plano la sigue.
3. **X / Y / Z** cambia la orientación del corte, la **rueda** lo inclina de 5 en 5°. **Clic** = separa ahí con los imanes. **Esc** = cancelar. (Ctrl + rueda y botón central siguen moviendo la vista.)

## Colocar a mano (desplegable «Colocar a mano / caras marcadas»)

1. Selecciona el modelo (modo Objeto).
2. «Separar por»: **Plano de corte** → elige la orientación inicial y pulsa «Añadir plano de corte». Muévelo y gíralo (G / R) hasta donde quieras separar. El plano puede estar inclinado.
3. Ajusta diámetro y grosor del imán, holgura y pared mínima. «Automática» pone dos imanes si caben; si no, uno.
4. «Separar y crear alojamientos»: salen `_Base` y `_Pieza` con los alojamientos enfrentados. El original queda oculto y el plano también.
5. Exporta las piezas seleccionadas o visibles a STL en mm.

¿Ya tenías caras marcadas de antes? Elige «Caras marcadas»: se leen de la malla sin entrar en Edición (el borde debe ser plano y la selección debe encerrar la parte que se separa).

Todas las medidas (imanes, espigas, holguras, tamaños) van en milímetros. «Unidades de entrada» se refiere a las coordenadas del modelo: «Escala de la escena» para escenas métricas normales; «1 unidad = 1 mm» para STL importados tal cual.

## Qué cambia respecto a 1.1

- Nada exige modo Edición: planos de corte y cortadores como objetos que mueves en modo Objeto.
- Las piezas vaciadas (cascos, bustos para espuma) se cortan bien: la tapa del corte queda en anillo y el hueco sigue hueco.
- Booleanas sin `bpy.ops` y con el solucionador «Manifold» de Blender 4.5+/5.x (mucho más rápido), con «Exacto» de respaldo.
- Exportación STL vectorizada: muy rápida con modelos de millones de caras.
- Si algo falla, se borra lo creado y el original sigue intacto; Ctrl+Z deshace una operación terminada.

## Límites

- El modelo debe ser una malla cerrada (manifold). Si no lo es, repáralo antes (por ejemplo en 3D LAB).
- La holgura de cortadores que no sean primitivas del complemento se aplica siguiendo las normales: es aproximada en esquinas.
- Imprime una muestra para ajustar holguras a tu impresora y material.
