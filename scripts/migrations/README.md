# Script de reparación - doble cifrado en Alumno

En el alta masiva de alumnos había un bug que cifraba dos veces los campos
dni, direccion y fecha_nacimiento. Por eso a algunos alumnos les aparecían
esos datos como texto raro (tipo gAAAAA...) en vez del valor real.

Solo pasaba con alumnos cargados por alta masiva, no con los cargados uno
por uno.

## Scripts

- `detectar_doble_cifrado.py` → revisa la tabla alumno y lista quiénes están
  afectados (no modifica nada).
- `reparar_doble_cifrado.py` → les saca la capa de cifrado de más a los
  afectados.

## Cómo correrlos

```bash
python detectar_doble_cifrado.py
python reparar_doble_cifrado.py
```

Antes de correr el de reparar, hacer backup de la tabla alumno.

## Estado

Ya se corrió y se arregló (24/09/2026). Eran 435 de 603 alumnos afectados,
quedaron todos reparados.

El bug de origen ya está arreglado en alumno_router.py (alta_masiva_alumnos_en_curso),
usando model_copy() en vez de reconstruir el objeto con model_dump().