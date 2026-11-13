-- Opcional: la app crea esta tabla automáticamente al primer arranque.
CREATE DATABASE IF NOT EXISTS fitplate CHARACTER SET utf8mb4;
USE fitplate;

CREATE TABLE IF NOT EXISTS plan_semanal (
    id INT AUTO_INCREMENT PRIMARY KEY,
    dia VARCHAR(12) NOT NULL UNIQUE,
    desayuno VARCHAR(255) NOT NULL DEFAULT '',
    comida VARCHAR(255) NOT NULL DEFAULT '',
    cena VARCHAR(255) NOT NULL DEFAULT '',
    snack VARCHAR(255) NOT NULL DEFAULT '',
    ejercicio VARCHAR(255) NOT NULL DEFAULT '',
    descanso_horas DECIMAL(4,2) NOT NULL DEFAULT 0,
    coste_desayuno DECIMAL(10,2) NOT NULL DEFAULT 0,
    coste_comida DECIMAL(10,2) NOT NULL DEFAULT 0,
    coste_cena DECIMAL(10,2) NOT NULL DEFAULT 0,
    coste_snack DECIMAL(10,2) NOT NULL DEFAULT 0,
    coste_diario DECIMAL(10,2) NOT NULL DEFAULT 0,   -- = suma de los 4 costes
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Presupuesto semanal:
-- SELECT SUM(coste_diario) AS budget_semanal FROM plan_semanal;
