# Investigación técnica y decisiones de diseño

Este documento resume las alternativas estudiadas para cada etapa, por qué se eligió cada
solución y qué se midió para comprobarlo. Las cifras proceden de `scripts/benchmark_smoothing.py`
y `scripts/report_scenarios.py` sobre los modelos sintéticos de `core/synthetic.py`.

## 1. Naturaleza del problema

Un escaneo plantar es una **superficie abierta y fina**, vista esencialmente desde un lado. Tres
propiedades condicionan todo el diseño:

1. No hay interior ni exterior: los métodos volumétricos pierden su principal ventaja.
2. La planta es un **campo de alturas** respecto a la dirección de escaneo, pero no es plana: el
   arco es una concavidad de más de un centímetro que debe conservarse.
3. La geometría espuria puede estar **conectada** a la planta (laterales del pie, soportes,
   láminas de registro defectuoso) o **superpuesta** a ella (capas duplicadas).

## 2. Segmentación y aislamiento de la planta

| Técnica | Qué aporta | Limitación en este caso | Decisión |
|---|---|---|---|
| Componentes conexos | Separa fragmentos flotantes. | No separa nada que esté conectado; "el mayor componente" puede incluir medio pie. | Solo como utilidad (islas, motas). |
| Crecimiento de regiones | Sigue la continuidad de la superficie; conserva el arco porque es continuo con el resto. | Necesita buenos criterios de parada y una semilla fiable. | **Núcleo del algoritmo.** |
| Segmentación por normales | La planta mira hacia el escáner; los laterales, no. | Sensible al ruido; un umbral único deja el borde dentado. | **Usada** con normales suavizadas e histéresis (semilla 35°, crecimiento 62°). |
| Segmentación por curvatura / pliegues | Las láminas espurias suelen unirse por un pliegue. | La curvatura discreta es ruidosa; los surcos de los dedos también son pliegues. | **Usada** como barrera de ángulo diedro alto (80°), no como criterio principal. |
| Topología (aristas no manifold) | Una arista con tres caras delata una lámina pegada a otra. | No todas las uniones espurias son no manifold. | **Usada** como barrera. |
| Agrupamiento espacial (DBSCAN, k-medias) | Agrupa puntos próximos. | Ignora la conectividad y junta capas cercanas, justo lo que hay que separar. | Descartado. |
| RANSAC (planos) | Detecta un suelo o una mesa. | La planta no es un plano y las zonas de apoyo sí lo parecen: riesgo de borrar talón o antepié. | Descartado; la orientación se obtiene de la normal media robusta. |
| Campos de distancia con signo / vóxeles | Robustos frente a topología defectuosa. | Sin interior definido, dos capas a 1,5 mm se funden salvo con vóxeles muy finos. | Descartado en 3D; se usa su análogo 2,5D (z-buffer). |
| Proximidad entre superficies / detección de capas | Identifica duplicados y geometría oculta. | Requiere una dirección de referencia. | **Usada**: rejilla de ocupación y visibilidad en la dirección plantar. |
| Corte de grafo (graph cut) sobre caras | Óptimo global con término de suavidad. | Necesita un solver de flujo máximo y una calibración de costes que solo tiene sentido con datos reales. | Candidato para una versión futura. |

### Algoritmo implementado (`core/segmentation.py`)

En el marco plantar (eje Z = dirección hacia el escáner):

1. **Normales suavizadas** por difusión sobre el grafo de caras, con un radio en milímetros.
2. **Barreras**: aristas no manifold y aristas con ángulo diedro mayor que el umbral.
3. **Visibilidad**: z-buffer de toda la malla; una cara oculta tras otra superficie no es planta.
4. **Semillas**: caras de poca pendiente agrupadas en islas. La principal es la más adelantada
   hacia el escáner entre las de área relevante (o la que el usuario señale con *Elegir planta*).
5. **Crecimiento por ondas con histéresis y rejilla de ocupación**: una cara se acepta si es
   candidata por pendiente, se llega a ella sin cruzar barreras y su celda no está ya ocupada por
   otra altura. Esto último impide que la región salte a una capa superpuesta **aunque esté
   conectada**, y es independiente de la altura absoluta: el arco se acepta porque llega por
   continuidad.
6. **Huella**: lo que cae dentro de la huella de la planta y no pertenece a ella es una capa
   superpuesta o geometría por encima o por debajo, y se elimina.
7. **Islas de extensión**: regiones plantares cercanas y coherentes en altura (dedos separados por
   un surco) se conservan como **dudosas**, se muestran en amarillo y generan un aviso.
8. **Puentes**: los huecos estrechos entre regiones conservadas se cubren con las caras reales
   visibles, no con interpolación.
9. Las **correcciones manuales** prevalecen siempre.

Cada cara eliminada lleva su motivo (pendiente, capa superpuesta, oculta, fragmento lejano…), que
se muestra en el informe para poder ajustar la tolerancia adecuada.

## 3. Reconstrucción de la superficie y del sólido

| Método | Ventajas | Inconvenientes aquí | Decisión |
|---|---|---|---|
| Poisson / Screened Poisson ([Kazhdan y Hoppe, 2013](https://www.hhoppe.com/screenedpoisson.pdf)) | Robusto al ruido; siempre estanco. | Está pensado para objetos cerrados: en una superficie abierta inventa una "tapa", tiende a unir capas finas y a puentear huecos, y suaviza de forma global sin control local. Requiere además normales fiables. | Descartado. |
| SDF + remallado por vóxeles | Garantiza malla manifold. | Memoria cúbica para llegar a décimas de milímetro; funde capas próximas; redondea el contorno. | Descartado en 3D. |
| Reparación directa (tipo MeshFix) | Conserva los vértices originales. | No resuelve capas duplicadas ni densidades dispares; licencia GPL. | Descartado. |
| Relleno de agujeros por triangulación + carenado | Local y fiel. | Requiere triangulación con restricciones y varias pasadas de carenado; frágil con bordes ruidosos. | Sustituido por el relleno sobre rejilla. |
| Offset de malla | Espesor uniforme real. | Se autointerseca en concavidades de radio menor que el espesor (el arco). | Sustituido por desplazamiento a lo largo de la dirección plantar. |
| Operaciones booleanas | Corte exacto con un prisma. | Necesitan una librería robusta (CGAL es GPL para este módulo) y entradas ya estancas. | Innecesarias con campo de alturas. |
| **Campo de alturas (2,5D)** | Exacto para una planta vista de frente; densidad uniforme; relleno y contorno son problemas 2D bien resueltos; el sólido extruido no puede autointersecarse. | No representa voladizos. | **Elegido.** |

### Implementación (`core/surface_remesh.py`, `core/mesh_reconstruction.py`)

- **Alturas**: rasterización de los triángulos originales con interpolación baricéntrica exacta
  (no se interpola entre puntos, se muestrea la superficie medida).
- **Agujeros**: carenado **biarmónico** (mínimos cuadrados del Laplaciano), que continúa la
  curvatura de alrededor en lugar de tender una membrana plana. En la prueba unitaria reproduce
  una superficie cuadrática con error menor que 0,05 mm en un agujero de 12 celdas de diámetro.
- **Contorno**: cierre, relleno, apertura y regularización de la huella; el borde escalonado de la
  rejilla se proyecta a la isolínea de la máscara difuminada y se alisa a lo largo del contorno con
  reproyección (no encoge). Un corte por plano queda recto; el resto, curvo y suave.
- **Altura del borde**: se toma de la geometría real contigua a la selección cuando existe y, si
  no, de un plano local ajustado por mínimos cuadrados. Una extrapolación "plana" levantaba el
  borde hasta 0,9 mm en zonas inclinadas; con este esquema el error RMS del primer anillo baja a
  0,10 mm en el modelo limpio.
- **Sólido**: copia inferior con la misma triangulación (base plana o paralela) y paredes
  verticales subdivididas en filas. Ángulo mínimo de triángulo típico: 15°.

## 4. Suavizado adaptativo

| Método | Comportamiento | Decisión |
|---|---|---|
| Laplaciano | Encoge: aplana el arco y redondea el borde. | Descartado (se usa solo como referencia en la comparativa). |
| Taubin (λ\|μ) | Evita el encogimiento global, pero filtra igual en todas partes y no distingue relieve de ruido. | Descartado. |
| HC (Vollmer et al.) | Laplaciano con corrección que devuelve el desplazamiento medio. | Su idea se reutiliza: se anula el desplazamiento de baja frecuencia en las zonas cóncavas. |
| Bilateral sobre vértices (Fleishman et al.; Jones et al.) | Preserva aristas vivas usando un núcleo de rango ([Jones, Durand y Desbrun, 2003](https://people.csail.mit.edu/thouis/JDD03.pdf)). | Se adopta el **peso de rango** como segunda pasada robusta. |
| Bilateral sobre normales ([Zheng et al., 2011](https://hongbofu.people.ust.hk/doc/bilateral_normal_filtering_tvcg11.pdf)) | El mejor en piezas con aristas vivas; dos fases (normales, luego vértices). | Un pie no tiene aristas vivas; su ventaja no compensa la complejidad. |
| Difusión anisótropa | Preserva rasgos según la curvatura. | Sensible a parámetros y cara de iterar. | Descartada. |
| **Regresión local cuadrática robusta (MLS)** | Reproduce exactamente la curvatura suave, por lo que no encoge; el residuo del ajuste es una medida directa del ruido local. | **Elegida.** |

La comparación publicada por [Beşdok y Çivicioğlu (2023)](https://doi.org/10.53093/mephoj.1349021)
entre filtros bilateral, Laplaciano y de Taubin sitúa al de Taubin como término medio entre la
preservación de detalle del bilateral y la suavidad del Laplaciano; aquí el criterio decisivo es
otro, no aplanar una concavidad grande y suave, y por eso se optó por un ajuste local de segundo
orden.

### Implementación (`core/smoothing.py`)

Para cada vértice se ajusta un polinomio cuadrático a sus vecinos dentro del radio de influencia:

- **Ruido local** = RMS del residuo del ajuste en el entorno. La intervención es
  `ruido² / (ruido² + umbral²)`: máxima donde hay ruido, casi nula donde la superficie ya es limpia.
- **Curvatura coherente** (Hessiano promediado): donde es alta frente al radio, se interviene menos.
- **Concavidad** (distancia a la envolvente convexa superior, el "puente" entre talón y antepié):
  en esas zonas se reduce la intervención y la tolerancia, y se resta el desplazamiento de baja
  frecuencia. El arco no puede rellenarse.
- **Pesos de rango**: segunda pasada que descarta vecinos al otro lado de un pliegue.
- **Tolerancia de desviación**: límite estricto por vértice.
- En mallas densas los vecinos se agrupan en celdas, de modo que el radio se respeta y el coste no
  crece con la densidad.

### Comparativa medida

Error respecto a la planta analítica, partiendo de la misma superficie recortada (≈ 48 000 caras de
entrada). "Sesgo arco" positivo significa que el arco se rellena.

| Escenario | Método | RMS (mm) | Sesgo arco (mm) | RMS dedos (mm) |
|---|---|---:|---:|---:|
| limpio | sin suavizar | 0,047 | −0,009 | 0,059 |
| limpio | Laplaciano, 10 iteraciones | 0,437 | +0,042 | 0,605 |
| limpio | Taubin, 20 iteraciones | 0,186 | +0,000 | 0,280 |
| limpio | **MLS adaptativo** | **0,042** | −0,009 | 0,077 |
| ruido σ=0,3–0,6 | sin suavizar | 0,366 | +0,022 | 0,443 |
| ruido σ=0,3–0,6 | Laplaciano, 10 iteraciones | 0,597 | +0,099 | 0,782 |
| ruido σ=0,3–0,6 | Taubin, 20 iteraciones | 0,335 | +0,036 | 0,415 |
| ruido σ=0,3–0,6 | **MLS adaptativo** | **0,217** | +0,021 | 0,268 |
| todos los defectos | sin suavizar | 0,189 | −0,005 | 0,177 |
| todos los defectos | Laplaciano, 10 iteraciones | 0,447 | +0,058 | 0,320 |
| todos los defectos | Taubin, 20 iteraciones | 0,222 | +0,003 | 0,179 |
| todos los defectos | **MLS adaptativo** | **0,106** | −0,007 | 0,111 |

Las versiones de Laplaciano y Taubin son las básicas (pesos uniformes, sin tratamiento especial del
borde), y buena parte de su error se concentra en el contorno y en los dedos. Con el modelo limpio,
el método elegido no empeora la superficie; con ruido fuerte reduce el error un 41 %. Sin las
protecciones (curvatura, arco, umbral de ruido, tolerancia) baja algo más con ruido (0,187 mm),
pero empeora el modelo limpio (0,053 mm) y el relieve de los dedos: de ahí los valores por defecto.

## 5. Librerías

| Librería | Licencia | Valoración |
|---|---|---|
| NumPy, SciPy | BSD | Suficientes para todo el núcleo: álgebra dispersa, k-d tree, morfología, envolvente convexa. **Elegidas.** |
| Trimesh | MIT | Muy cómoda para E/S y consultas, pero las operaciones clave (booleanas, reparación) delegan en motores externos. Prescindible. |
| Open3D | MIT | Poisson, remallado por vóxeles y Taubin; ninguno es el método adecuado aquí. Paquete pesado y dependiente de la versión de Python. |
| PyMeshLab | GPL v3 | Catálogo enorme de filtros; la licencia condiciona la distribución del producto. |
| CGAL (Polygon Mesh Processing) | GPL / comercial | Referencia en robustez; licencia y compilación complejas. |
| libigl | MPL 2.0 en su núcleo; los módulos que enlazan con CGAL heredan copyleft ([licencia](https://libigl.github.io/license)) | Buena opción futura para operadores cotangente o booleanas. |
| MeshFix / pymeshfix | GPL v3 | Repara agujeros y autointersecciones, pero no resuelve capas ni segmentación. |
| PyVista / VTK | MIT / BSD | Excelente visualización de escritorio; el pincel sobre caras en web requiere igualmente un visor propio. |
| Blender (bpy) | GPL | Excesivo como dependencia. |
| Streamlit / Gradio | Apache 2.0 | No permiten pintar caras ni mover un plano de corte en vivo sobre el modelo. |
| FastAPI | MIT | Equivalente a Starlette (sobre la que está construida) más validación que aquí no se necesita. |
| **Starlette + Uvicorn** | BSD | Servidor mínimo y estable. **Elegidos.** |
| Three.js | MIT | Estándar para WebGL; exige incluir la librería o depender de un CDN. |
| **Visor WebGL2 propio** | — | 350 líneas, sin dependencias ni conexión; selección de caras por búfer de identificadores, que hace natural un pincel que solo pinta lo visible. **Elegido.** |

Resultado: cuatro dependencias con ruedas precompiladas para macOS (Intel y Apple Silicon), todas
con licencia permisiva. Los algoritmos están vectorizados; un escaneo de 515 000 caras se procesa
completo en unos 37 s.

## 6. Arquitectura

```
navegador (visor WebGL2, herramientas) ── HTTP local ── app/server.py ── core/pipeline.py ── core/*
```

- `core/` no conoce la interfaz: se usa igual desde la web, la línea de comandos y las pruebas.
- `Pipeline` guarda las etapas (original → segmentado → recortado → suavizado → sólido); rehacer
  una etapa invalida las posteriores y conserva las anteriores.
- El servidor mantiene una única sesión en memoria y serializa las operaciones (uso local).
- Las mallas viajan en binario (Float32/Uint32) y las etiquetas como un byte por cara.

## 7. Referencias

- G. Taubin, *A signal processing approach to fair surface design*, SIGGRAPH 1995.
- J. Vollmer, R. Mencl, H. Müller, *Improved Laplacian smoothing of noisy surface meshes*, Eurographics 1999.
- S. Fleishman, I. Drori, D. Cohen-Or, *Bilateral mesh denoising*, SIGGRAPH 2003.
- T. Jones, F. Durand, M. Desbrun, *Non-iterative, feature-preserving mesh smoothing*, SIGGRAPH 2003. <https://people.csail.mit.edu/thouis/JDD03.pdf>
- Y. Zheng, H. Fu, O. K.-C. Au, C.-L. Tai, *Bilateral normal filtering for mesh denoising*, IEEE TVCG 2011. <https://hongbofu.people.ust.hk/doc/bilateral_normal_filtering_tvcg11.pdf>
- E. Beşdok, P. Çivicioğlu, *Analysing detail preserving capabilities of bilateral, Laplacian and Taubin mesh filtering methods*, Mersin Photogrammetry Journal 2023. <https://doi.org/10.53093/mephoj.1349021>
- M. Kazhdan, H. Hoppe, *Screened Poisson surface reconstruction*, ACM TOG 2013. <https://www.hhoppe.com/screenedpoisson.pdf>
- D. Levin, *Mesh-independent surface interpolation*, 2003 (mínimos cuadrados móviles).
- P. Liepa, *Filling holes in meshes*, SGP 2003.
- M. Botsch, L. Kobbelt, *A remeshing approach to multiresolution modeling*, SGP 2004.
- Licencia de libigl: <https://libigl.github.io/license>
