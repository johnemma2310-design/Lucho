-- Esquema de base de datos de Lucho, asistente académico por WhatsApp
-- Universidad Católica Luis Amigó
-- Ejecutar una sola vez sobre una base de datos PostgreSQL vacía (Neon, Supabase o local).

CREATE TABLE IF NOT EXISTS estudiantes (
  id SERIAL PRIMARY KEY,
  telefono TEXT UNIQUE NOT NULL,
  nombre TEXT,
  correo TEXT UNIQUE,
  correo_pendiente TEXT,  -- correo escrito pero aún sin verificar
  programa TEXT,
  -- nuevo | esperando_aceptacion | esperando_correo | esperando_codigo | esperando_nombre
  -- | esperando_programa | activo | confirmando_eliminacion
  estado_registro TEXT NOT NULL DEFAULT 'nuevo',
  acepto_datos_at TIMESTAMPTZ,
  otp_hash TEXT,
  otp_expira TIMESTAMPTZ,
  otp_intentos INT NOT NULL DEFAULT 0,
  bloqueado_hasta TIMESTAMPTZ,
  resumen_diario BOOLEAN NOT NULL DEFAULT TRUE,
  hora_resumen TIME NOT NULL DEFAULT '06:00',
  resumen_semanal BOOLEAN NOT NULL DEFAULT FALSE,
  aviso_clase BOOLEAN NOT NULL DEFAULT FALSE,
  minutos_aviso_clase INT NOT NULL DEFAULT 15 CHECK (minutos_aviso_clase BETWEEN 5 AND 120),
  ultimo_mensaje_at TIMESTAMPTZ,
  creado_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- dia_semana: 1 = lunes ... 7 = domingo
CREATE TABLE IF NOT EXISTS clases (
  id SERIAL PRIMARY KEY,
  estudiante_id INT NOT NULL REFERENCES estudiantes(id) ON DELETE CASCADE,
  materia TEXT NOT NULL,
  grupo TEXT,
  dia_semana SMALLINT NOT NULL CHECK (dia_semana BETWEEN 1 AND 7),
  hora_inicio TIME NOT NULL,
  hora_fin TIME NOT NULL,
  salon TEXT,
  bloque TEXT,
  docente TEXT,
  CHECK (hora_fin > hora_inicio)
);
CREATE INDEX IF NOT EXISTS idx_clases_estudiante_dia ON clases(estudiante_id, dia_semana);

-- Lo que la IA extrajo de un PDF, foto o texto y el estudiante aún no confirma (CU-05)
CREATE TABLE IF NOT EXISTS borradores_horario (
  estudiante_id INT PRIMARY KEY REFERENCES estudiantes(id) ON DELETE CASCADE,
  datos JSONB NOT NULL,
  creado_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS recordatorios (
  id SERIAL PRIMARY KEY,
  estudiante_id INT NOT NULL REFERENCES estudiantes(id) ON DELETE CASCADE,
  tipo TEXT NOT NULL DEFAULT 'nota' CHECK (tipo IN ('parcial','entrega','quiz','nota')),
  titulo TEXT NOT NULL,
  materia TEXT,
  fecha_evento TIMESTAMPTZ NOT NULL,
  completado BOOLEAN NOT NULL DEFAULT FALSE,
  creado_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_recordatorios_estudiante ON recordatorios(estudiante_id, fecha_evento);

CREATE TABLE IF NOT EXISTS avisos (
  id SERIAL PRIMARY KEY,
  recordatorio_id INT NOT NULL REFERENCES recordatorios(id) ON DELETE CASCADE,
  enviar_at TIMESTAMPTZ NOT NULL,
  enviado BOOLEAN NOT NULL DEFAULT FALSE,
  intentos INT NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_avisos_pendientes ON avisos(enviar_at) WHERE NOT enviado;

-- Evita mandar dos veces el mismo resumen o aviso de clase
CREATE TABLE IF NOT EXISTS envios_log (
  estudiante_id INT NOT NULL REFERENCES estudiantes(id) ON DELETE CASCADE,
  tipo TEXT NOT NULL,
  clave TEXT NOT NULL,
  enviado_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (estudiante_id, tipo, clave)
);

-- Historial corto de conversación para dar contexto a la IA
CREATE TABLE IF NOT EXISTS mensajes (
  id BIGSERIAL PRIMARY KEY,
  estudiante_id INT NOT NULL REFERENCES estudiantes(id) ON DELETE CASCADE,
  rol TEXT NOT NULL CHECK (rol IN ('user','model')),
  contenido TEXT NOT NULL,
  creado_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_mensajes_estudiante ON mensajes(estudiante_id, creado_at DESC);

-- WhatsApp puede reenviar el mismo webhook; esto evita procesarlo dos veces
CREATE TABLE IF NOT EXISTS mensajes_procesados (
  wa_message_id TEXT PRIMARY KEY,
  recibido_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Festivos y vacaciones: ese día no se mandan resúmenes ni avisos de clase
CREATE TABLE IF NOT EXISTS dias_no_habiles (
  fecha DATE PRIMARY KEY,
  descripcion TEXT NOT NULL
);

-- Información institucional para responder preguntas (CU-13, CU-15)
CREATE TABLE IF NOT EXISTS documentos_fragmentos (
  id SERIAL PRIMARY KEY,
  documento TEXT NOT NULL,
  contenido TEXT NOT NULL,
  activo BOOLEAN NOT NULL DEFAULT TRUE,
  busqueda TSVECTOR GENERATED ALWAYS AS (to_tsvector('spanish', documento || ' ' || contenido)) STORED,
  creado_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_documentos_busqueda ON documentos_fragmentos USING GIN (busqueda);

-- Festivos de Colombia restantes de 2026 (agregar los de 2027 y las vacaciones del calendario académico)
INSERT INTO dias_no_habiles (fecha, descripcion) VALUES
  ('2026-10-12', 'Festivo: Día de la Raza'),
  ('2026-11-02', 'Festivo: Todos los Santos'),
  ('2026-11-16', 'Festivo: Independencia de Cartagena'),
  ('2026-12-08', 'Festivo: Inmaculada Concepción'),
  ('2026-12-25', 'Festivo: Navidad')
ON CONFLICT (fecha) DO NOTHING;
