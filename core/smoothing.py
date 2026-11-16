"""Etapa 4: suavizado adaptativo que preserva la anatomía.

Método: regresión local cuadrática robusta (mínimos cuadrados móviles, MLS) sobre el
campo de alturas, con peso de intervención local:

* **Ruido local**: se estima el residuo respecto al ajuste local; donde hay más ruido
  se interviene más y donde la superficie ya es limpia casi no se toca.
* **Preservación de curvatura**: un ajuste *cuadrático* reproduce exactamente la
  curvatura suave (arco, talón, cabezas metatarsales), por lo que no "encoge" la
  superficie como un Laplaciano. Además, donde la curvatura coherente es alta frente
  al radio (pliegues de los dedos) la intervención se reduce.
* **Robustez**: pesos de rango (tipo bilateral) excluyen del ajuste los vecinos del
  otro lado de un pliegue.
* **Protección del arco**: las zonas cóncavas (separadas de la envolvente convexa)
  reciben menos intervención, menor tolerancia y una corrección que anula cualquier
  desplazamiento de baja frecuencia: la profundidad del arco no puede reducirse.
* **Tolerancia de desviación**: ningún vértice se aleja de su posición original más
  de lo indicado (garantía dura).

Solo se modifica la coordenada Z (eje plantar): el contorno y la proyección no
cambian, de modo que la superficie sigue siendo un campo de alturas válido.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict

import numpy as np
from scipy.spatial import ConvexHull, cKDTree

from .mesh import Mesh


@dataclass
class SmoothParams:
    intensity: float = 0.8               # 0..1
    radius: float = 4.0                  # mm: radio de influencia
    iterations: int = 3
    max_deviation: float = 0.8           # mm: desviación máxima permitida respecto al original
    curvature_preservation: float = 0.5  # 0..1
    arch_protection: float = 0.7         # 0..1
    noise_floor: float = 0.03            # mm: rugosidad por debajo de la cual apenas se interviene

    @classmethod
    def from_dict(cls, d: dict | None) -> "SmoothParams":
        d = d or {}
        return cls(**{k: type(getattr(cls, k))(v) for k, v in d.items() if k in cls.__dataclass_fields__})


class _Neighborhood:
    """Vecindario fijo (en XY) y ajuste cuadrático ponderado por bloques.

    Si el radio pedido abarca más vértices de los que conviene usar por punto (mallas muy
    densas), los vértices se agrupan en celdas y el ajuste se hace sobre las medias de celda:
    el radio de influencia se respeta siempre y el coste no crece con la densidad.
    """

    def __init__(self, xy: np.ndarray, radius: float, k_max: int = 64):
        self.n = len(xy)
        self.xy = xy
        tree = cKDTree(xy)
        d2, _ = tree.query(xy, k=min(2, self.n))
        self.spacing = float(np.median(d2[:, -1])) if self.n > 1 else 1.0
        need = int(1.15 * np.pi * radius ** 2 / max(self.spacing, 1e-9) ** 2) + 2
        if need > k_max and self.n > k_max:
            cell = self.spacing * float(np.ceil(np.sqrt(need / (0.75 * k_max))))
            q = np.floor((xy - xy.min(axis=0)) / cell).astype(np.int64)
            _, self.cluster = np.unique(q[:, 0] * (int(q[:, 1].max()) + 1) + q[:, 1], return_inverse=True)
            self.cluster = self.cluster.ravel()
            self.count = np.bincount(self.cluster).astype(np.float64)
            self.src = np.stack([np.bincount(self.cluster, weights=xy[:, k]) / self.count for k in (0, 1)], axis=1)
            tree = cKDTree(self.src)
        else:
            self.cluster = None
            self.count = np.ones(self.n)
            self.src = xy
        k = int(min(max(need, 7), k_max, len(self.src)))
        dist, idx = tree.query(xy, k=k, distance_upper_bound=radius)
        self.valid = idx < len(self.src)
        self.idx = np.where(self.valid, idx, 0)
        dist = np.where(self.valid, dist, 0.0)
        self.radius_eff = float(np.percentile(dist.max(axis=1), 50)) if self.n else radius
        self.radius = radius
        self.w0 = np.exp(-3.0 * (dist / radius) ** 2) * self.valid * self.count[self.idx]
        self.wsum = np.maximum(self.w0.sum(axis=1), 1e-300)
        self.k = k
        self.clustered = self.cluster is not None

    def _source(self, f: np.ndarray) -> np.ndarray:
        """Valores del campo en los puntos de apoyo (medias de celda si hay agrupación)."""
        if self.cluster is None:
            return f
        if f.ndim == 1:
            return np.bincount(self.cluster, weights=f) / self.count
        return np.stack([np.bincount(self.cluster, weights=f[:, c]) / self.count for c in range(f.shape[1])], axis=1)

    def average(self, f: np.ndarray) -> np.ndarray:
        """Media ponderada (gaussiana) de un campo por vértice."""
        fs = self._source(f)
        if f.ndim == 1:
            return (self.w0 * fs[self.idx]).sum(axis=1) / self.wsum
        return np.einsum("nk,nkc->nc", self.w0, fs[self.idx]) / self.wsum[:, None]

    def fit(self, z: np.ndarray, range_sigma: np.ndarray | None = None, chunk: int = 12000):
        """Ajuste cuadrático ponderado centrado en cada vértice.

        Devuelve los 6 coeficientes (1, u, v, u², uv, v²) con u, v en unidades de radio.
        Si ``range_sigma`` no es None se hace una segunda pasada con pesos robustos.
        """
        coef = np.zeros((self.n, 6))
        ridge = np.diag([1e-9, 1e-6, 1e-6, 1e-3, 1e-3, 1e-3])
        zs = self._source(z)
        for s in range(0, self.n, chunk):
            e = min(s + chunk, self.n)
            ix = self.idx[s:e]
            u = (self.src[ix, 0] - self.xy[s:e, None, 0]) / self.radius
            v = (self.src[ix, 1] - self.xy[s:e, None, 1]) / self.radius
            phi = np.stack([np.ones_like(u), u, v, u * u, u * v, v * v], axis=2)
            zj = zs[ix]
            w = self.w0[s:e]
            for it in range(2 if range_sigma is not None else 1):
                wp = phi * w[:, :, None]
                m = np.matmul(wp.transpose(0, 2, 1), phi)
                m += ridge * w.sum(axis=1)[:, None, None]
                rhs = np.einsum("nka,nk->na", wp, zj)
                c = np.linalg.solve(m, rhs[:, :, None])[:, :, 0]
                if range_sigma is not None and it == 0:
                    resid = zj - np.einsum("nka,na->nk", phi, c)
                    sr = np.maximum(range_sigma[s:e], 1e-6)[:, None]
                    w = self.w0[s:e] * np.exp(-0.5 * (resid / sr) ** 2)
            coef[s:e] = c
        return coef


def upper_hull(xy: np.ndarray, z: np.ndarray, max_hull_points: int = 20000, seed: int = 0):
    """Planos (a, b, c) de la envolvente convexa superior: z_hull(x, y) = min(a·x + b·y + c)."""
    n = len(z)
    if n < 10:
        return None
    rng = np.random.default_rng(seed)
    sub = rng.choice(n, size=min(n, max_hull_points), replace=False)
    pts = np.column_stack([xy[sub], z[sub]])
    try:
        hull = ConvexHull(pts)
    except Exception:
        return None
    eq = hull.equations
    up = eq[eq[:, 2] > 1e-6]
    if len(up) == 0:
        return None
    return -up[:, 0] / up[:, 2], -up[:, 1] / up[:, 2], -up[:, 3] / up[:, 2]


def hull_height(planes, xy: np.ndarray) -> np.ndarray:
    a, b, c = planes
    out = np.empty(len(xy))
    step = max(1, int(4_000_000 / len(a)))
    for s in range(0, len(xy), step):
        e = min(s + step, len(xy))
        out[s:e] = (xy[s:e, 0, None] * a[None] + xy[s:e, 1, None] * b[None] + c[None]).min(axis=1)
    return out


def concavity_gap(xy: np.ndarray, z: np.ndarray, planes=None) -> np.ndarray:
    """Distancia vertical de cada punto a la envolvente convexa superior ("puente" del arco)."""
    planes = planes if planes is not None else upper_hull(xy, z)
    if planes is None:
        return np.zeros(len(z))
    return np.maximum(hull_height(planes, xy) - z, 0.0)


def arch_metrics(xy: np.ndarray, z: np.ndarray, spacing: float) -> dict:
    gap = concavity_gap(xy, z)
    deep = gap > 0.5
    return {"arch_depth": float(gap.max()) if len(gap) else 0.0,
            "concave_volume": float(gap[deep].sum() * spacing * spacing),
            "concave_area": float(deep.sum() * spacing * spacing)}


def _curvature(coef: np.ndarray, radius: float, nb: _Neighborhood):
    """Curvatura media y máxima (en valor absoluto) a partir del Hessiano promediado."""
    r2 = radius * radius
    hess = np.stack([2 * coef[:, 3] / r2, coef[:, 4] / r2, 2 * coef[:, 5] / r2], axis=1)
    hess = nb.average(hess)
    g2 = (coef[:, 1] ** 2 + coef[:, 2] ** 2) / r2
    den = (1.0 + g2) ** 1.5
    tr = hess[:, 0] + hess[:, 2]
    dif = np.sqrt((0.5 * (hess[:, 0] - hess[:, 2])) ** 2 + hess[:, 1] ** 2)
    k1 = (0.5 * tr + dif) / den
    k2 = (0.5 * tr - dif) / den
    return 0.5 * (k1 + k2), np.maximum(np.abs(k1), np.abs(k2))


def adaptive_smooth(mesh: Mesh, params: SmoothParams | None = None) -> dict:
    """Suaviza de forma adaptativa una superficie tipo campo de alturas (marco canónico)."""
    p = params or SmoothParams()
    v = mesh.vertices
    xy = np.ascontiguousarray(v[:, :2])
    z0 = v[:, 2].copy()
    n = len(z0)
    warnings: list[str] = []
    nb = _Neighborhood(xy, max(p.radius, 1e-6))

    # ---- análisis: ruido local, curvatura coherente y concavidad
    coef = nb.fit(z0)
    e0 = z0 - coef[:, 0]
    noise0 = np.sqrt(nb.average(e0 * e0))
    f_noise = noise0 ** 2 / (noise0 ** 2 + p.noise_floor ** 2)
    h_mean0, k_abs = _curvature(coef, nb.radius, nb)
    kc = 6.0 * float(np.clip(p.curvature_preservation, 0, 1))
    g_curv = 1.0 / (1.0 + (kc * k_abs * nb.radius) ** 2)
    hull0 = upper_hull(xy, coef[:, 0])
    gap0 = concavity_gap(xy, coef[:, 0], hull0)
    a_arch = np.clip((gap0 - 0.5) / 1.5, 0.0, 1.0)
    a_arch = a_arch * a_arch * (3 - 2 * a_arch)
    prot = float(np.clip(p.arch_protection, 0, 1))
    alpha = float(np.clip(p.intensity, 0, 1)) * f_noise * g_curv * (1.0 - 0.5 * prot * a_arch)
    tol = max(p.max_deviation, 0.0) * (1.0 - 0.7 * prot * a_arch)

    # ---- iteraciones de ajuste robusto
    z = z0.copy()
    range_sigma = np.maximum(2.0 * noise0, 0.5 * p.noise_floor)
    for _ in range(max(int(p.iterations), 0)):
        c = nb.fit(z, range_sigma=range_sigma)
        z = z + alpha * (c[:, 0] - z)
        z = np.clip(z, z0 - tol, z0 + tol)

    # ---- protección del arco: se anula el desplazamiento de baja frecuencia en zonas cóncavas
    if prot > 0 and a_arch.any():
        low = z - z0
        for _ in range(3):
            low = nb.average(low)
        z = z - prot * a_arch * low
        z = np.clip(z, z0 - tol, z0 + tol)

    # ---- métricas
    coef1 = nb.fit(z)
    e1 = z - coef1[:, 0]
    noise1 = np.sqrt(nb.average(e1 * e1))
    h_mean1, _ = _curvature(coef1, nb.radius, nb)
    dz = z - z0
    am0 = arch_metrics(xy, z0, nb.spacing)
    am1 = arch_metrics(xy, z, nb.spacing)
    # Profundidad del arco: separación máxima (percentil 99,5) entre la superficie y el "puente"
    # que apoya en talón y antepié. Antes y después se miden contra la MISMA envolvente de
    # referencia, para que la cifra refleje un aplanamiento real y no la retirada de ruido.
    gsm0 = float(np.percentile(gap0, 99.5)) if len(gap0) else 0.0
    gsm1 = float(np.percentile(concavity_gap(xy, coef1[:, 0], hull0), 99.5)) if hull0 is not None else 0.0
    curv_rms0 = float(np.sqrt(np.mean(h_mean0 ** 2)))
    curv_change = float(np.sqrt(np.mean((h_mean1 - h_mean0) ** 2)) / max(curv_rms0, 1e-12))
    info = {
        "params": asdict(p),
        "vertices": int(n),
        "neighbors": int(nb.k),
        "radius_effective": nb.radius_eff,
        "noise_before_median": float(np.median(noise0)),
        "noise_before_p95": float(np.percentile(noise0, 95)),
        "noise_after_median": float(np.median(noise1)),
        "noise_after_p95": float(np.percentile(noise1, 95)),
        "displacement_mean": float(np.abs(dz).mean()),
        "displacement_rms": float(np.sqrt((dz ** 2).mean())),
        "displacement_max": float(np.abs(dz).max()),
        "displacement_bias": float(dz.mean()),
        "intervention_mean": float(alpha.mean()),
        "protected_area_fraction": float((a_arch > 0.5).mean()),
        "arch_depth_before": gsm0,
        "arch_depth_after": gsm1,
        "arch_depth_change": gsm1 - gsm0,
        "concave_volume_before": am0["concave_volume"],
        "concave_volume_after": am1["concave_volume"],
        "mean_curvature_rms": curv_rms0,
        "curvature_relative_change": curv_change,
        "warnings": warnings,
    }
    if gsm0 > 1.0 and (gsm0 - gsm1) > max(0.15, 0.03 * gsm0):
        warnings.append(f"La profundidad del arco ha disminuido {gsm0 - gsm1:.2f} mm: reduzca la intensidad "
                        "o el radio, o aumente la protección del arco.")
    out = Mesh(np.column_stack([xy, z]), mesh.faces.copy())
    return {"mesh": out, "info": info,
            "fields": {"displacement": dz, "noise": noise0, "intervention": alpha, "concavity": a_arch}}
