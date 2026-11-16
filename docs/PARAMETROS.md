# Parámetros

Todos los valores están en milímetros o grados (el programa convierte el STL a mm al cargarlo).
En la interfaz aparecen en el panel **Parámetros**; en la línea de comandos se pasan con
`--config archivo.json`:

```json
{
  "segment": {"max_angle": 68, "layer_tol": 1.0},
  "cut":     {"resolution": 0.6, "contour_inset": 1.0},
  "smooth":  {"intensity": 0.6, "radius": 5},
  "solid":   {"thickness": 8, "mode": "offset", "side": "exterior"}
}
```

## Segmentación (`segment`)

| Parámetro | Por defecto | Efecto | Cuándo cambiarlo |
|---|---:|---|---|
| `seed_angle` | 35° | Pendiente máxima, respecto a la dirección plantar, de las caras "claramente plantares" desde las que se inicia la región. | Bájelo si una superficie inclinada ajena se toma como planta. |
| `max_angle` | 62° | Pendiente hasta la que crece la región. Marca dónde termina la planta y empieza el lateral del pie. | Súbalo (70–75°) para conservar más borde y arco medial; bájelo si sube demasiado por los laterales. |
| `crease_angle` | 80° | Ángulo entre caras vecinas que actúa como barrera de continuidad (pliegue). | Bájelo (50–60°) si una lámina espuria unida por un pliegue suave se cuela; súbalo si surcos reales cortan la planta. |
| `layer_tol` | 1,5 mm | Separación a partir de la cual dos superficies en la misma posición son capas distintas. | Bájelo si hay capas duplicadas muy próximas; súbalo con escaneos muy ruidosos. |
| `gap_tol` | 6 mm | Distancia máxima a la planta para conservar una isla (p. ej. un dedo) como *dudosa*. | Súbalo si se pierden los dedos; bájelo si se cuelan fragmentos cercanos. |
| `join_dz` | 4 mm | Salto de altura máximo entre la isla y la planta. | Igual que el anterior, en altura. |
| `bridge_gap` | 5 mm | Anchura máxima de los huecos entre regiones conservadas que se puentean con caras reales (surcos). `0` lo desactiva. | Súbalo si quedan grietas entre dedos y antepié. |
| `min_island_area` | 25 mm² | Las islas conservadas más pequeñas se descartan. | Súbalo si quedan motas. |
| `normal_radius` | 3 mm | Escala de suavizado de las normales antes de medir pendientes. | Súbalo con mucho ruido; bájelo para respetar detalle fino en el borde. |
| `grid` | 1 mm | Resolución de la rejilla de ocupación y visibilidad (solo por configuración). | Rara vez. |

## Contorno y remallado (`cut`)

| Parámetro | Por defecto | Efecto | Cuándo cambiarlo |
|---|---:|---|---|
| `resolution` | 0 (auto) | Tamaño de arista de la malla reconstruida. Automático = 0,8 × la arista mediana del escaneo, acotado entre L/700 y L/150. | Bájelo para más detalle (más caras y tiempo); súbalo para mallas ligeras. |
| `contour_close` | 2 mm | Radio de cierre: une grietas y muescas del borde más estrechas que el doble del radio. | Súbalo para unir dedos; bájelo para respetar muescas reales. |
| `contour_open` | 1,5 mm | Radio de apertura: elimina picos y lenguas finas del borde. | Súbalo si el borde tiene salientes. |
| `contour_smooth` | 2 mm | Regularización del trazado del contorno. `0` la desactiva. | Súbalo para un contorno más redondeado. |
| `contour_inset` | 0 mm | Retranquea el borde hacia el interior. | Para descartar una banda de borde poco fiable. |
| `max_hole_area` | 0 | Área máxima de agujero que se rellena. `0` = todos (necesario para obtener un único contorno). | Si no quiere interpolar agujeros grandes (la superficie tendrá entonces varios contornos y el sólido, orificios pasantes). |
| `boundary_iters` | 10 | Iteraciones de alisado del borde con reproyección (solo por configuración). | Rara vez. |
| `layer_tol` | 1,5 mm | Si quedan dos capas en una celda más separadas que el doble de este valor, se toma la exterior y se avisa (solo por configuración). | Rara vez. |

Los planos de corte se indican aparte: `"planes": [{"point": [x, y, z], "normal": [nx, ny, nz]}]`,
en milímetros y en el marco del archivo; se conserva el lado hacia el que apunta la normal.

## Suavizado adaptativo (`smooth`)

| Parámetro | Por defecto | Efecto | Cuándo cambiarlo |
|---|---:|---|---|
| `intensity` | 0,8 | Intensidad global (0 = no tocar, 1 = sustituir por el ajuste local donde hay ruido). | Bájela si el escaneo es limpio. |
| `radius` | 4 mm | Radio de influencia: las irregularidades de escala menor se tratan como ruido. | Súbalo (5–6) con mucho ruido; bájelo (2–3) para conservar relieve fino. Por encima de 6 mm empieza a alterar el relieve de los dedos. |
| `iterations` | 3 | Pasadas del ajuste robusto. `0` desactiva el suavizado. | Más pasadas = más limpieza, algo más lento. |
| `max_deviation` | 0,8 mm | Tolerancia de desviación: ningún punto se aleja más que esto de su posición antes de suavizar (límite estricto). | Ajústelo a la precisión que necesite garantizar. |
| `curvature_preservation` | 0,5 | Reduce la intervención donde la curvatura coherente es alta (pliegues de los dedos, bordes del talón). | Súbalo si se redondean relieves; bájelo en escaneos muy ruidosos. |
| `arch_protection` | 0,7 | En las zonas cóncavas reduce la intervención y la tolerancia, y anula el desplazamiento de baja frecuencia. | Con `1` el arco queda prácticamente intacto. |
| `noise_floor` | 0,03 mm | Rugosidad local por debajo de la cual apenas se interviene. | Súbalo para no tocar zonas de buena calidad; bájelo para alisar también el ruido fino. |

El suavizado solo modifica la coordenada a lo largo de la dirección plantar; el contorno y la
triangulación no cambian.

## Sólido cerrado (`solid`)

| Parámetro | Por defecto | Efecto |
|---|---:|---|
| `thickness` | 5 mm | Espesor. Con base plana es el espesor **mínimo** (bajo el punto más saliente); con espesor uniforme es constante. |
| `mode` | `flat` | `flat`: base plana perpendicular a la dirección plantar. `offset`: copia de la superficie desplazada (espesor uniforme medido en esa dirección). |
| `side` | `interior` | `interior`: el material queda hacia el interior del pie (positivo de la planta). `exterior`: el material queda bajo la planta (plantilla o negativo). |
| `wall_rows` | 0 (auto) | Filas de triángulos de las paredes (solo por configuración). |

## Orientación

No es un parámetro numérico: **Invertir lado plantar** cambia el sentido de la dirección plantar y
**Planta = vista actual** la fija según la vista del visor. En la línea de comandos, `--flip`.
`--unit-scale` fuerza el factor a milímetros si la detección automática de unidades falla.
