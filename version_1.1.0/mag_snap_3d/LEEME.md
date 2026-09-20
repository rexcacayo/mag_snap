# MagSnap 3D 1.1.0

Paquete clásico de Blender, preparado y probado con Blender 5.2.1 LTS en Windows.
No requiere pip, servicios externos ni BigPrint.

## Instalar

1. No descomprimas el ZIP.
2. En Blender abre Editar > Preferencias > Complementos.
3. Abre el menú de la esquina superior derecha y elige Instalar desde disco / Install from Disk.
4. Selecciona mag_snap_3d-1.1.0.zip y activa el complemento si no se activa automáticamente.
5. En Vista 3D abre la barra lateral con N y busca MagSnap 3D.

Si tienes una versión anterior del mismo complemento, desactívala antes de actualizar y reinicia Blender para descargar las clases antiguas. Este paquete no cambia BigPrint.

## Uso

En modo Edición selecciona la región completa que quieres separar. Su borde debe ser un único contorno plano. Ajusta diámetro, grosor, holgura y pared mínima. Automática intenta dos alojamientos; usa uno si dos no caben en el contorno. Exporta después las piezas seleccionadas desde modo Objeto.

Todos los valores de agujeros, espigas, holguras y profundidad se introducen como números en milímetros. Unidades de entrada se refiere a las coordenadas del MODELO: elige Escala de la escena para una escena métrica normal; 1 unidad = 1 mm para STL importados conservando sus coordenadas numéricas en mm.

Las separaciones e insertos trabajan en copias y conservan el original oculto (también oculto al renderizar). Puedes recuperarlo desde el Outliner. Ante un fallo se eliminan solo los objetos temporales recién creados y se vuelve al original en modo Edición. Deshacer permite revertir una operación terminada.

La exportación usa la malla evaluada y las transformaciones en memoria, escribe STL en mm y no aplica transformaciones al original. Normaliza los nombres para Windows. Si existe un archivo, crea un nombre con sufijo; no lo sobrescribe. Los objetos con materiales distintos por cara deben separarse antes de exportar por color.

## Condiciones de la geometría

- Una sola malla cerrada en modo Edición; una región seleccionada y un único borde de separación.
- Para alojamientos, el borde debe ser plano (tolerancia geométrica de 0,02 mm). Puede estar inclinado respecto de los ejes: los cilindros se orientan con el borde.
- Los modificadores activos deben aplicarse previamente en una copia. La exportación sí evalúa los modificadores sin aplicarlos.
- Se comprueba el espacio disponible en el contorno y el espesor mediante muestras. Formas muy cóncavas, autointersecciones y detalles menores que el muestreo requieren revisión adicional.
- Los insertos admiten parches curvos regulares. La holgura sigue las normales y es aproximada en esquinas o concavidades; no es un offset CAD de distancia exacta. Conviene imprimir una muestra para ajustar el encaje a la máquina y material.
- Los alojamientos no incluyen imanes físicos ni ejecutan acciones sobre el laminador.

## Cambios respecto a 1.0

Correcciones de API para Blender 5.2, conversión a mm, materiales independientes del idioma, exportación sin alterar originales y sin sobrescribir archivos. Separación transaccional con validación de geometría, cortes orientados, espigas horizontales y control de espesor.

El código fuente completo está dentro del paquete; los tres ZIP son independientes.
