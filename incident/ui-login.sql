-- Browser login for the incident fixture owner (make incident-up UI=1).
-- Local Compose demo data only: oncall@otterworks.dev / OnCall-Demo-1.
-- The id is incident/scenarios.yaml seed.owner_id, so "My documents" lists the
-- 400 seeded documents the n-plus-one load pages on.
INSERT INTO users (id, email, password_hash, display_name, email_verified)
VALUES (
    '6d0c5f5e-7f0f-4a4e-9d0c-1a1c1d3a7000',
    'oncall@otterworks.dev',
    '$2a$12$g6ql9pDqtT4Of.a31rXVYeMccwhnOpXtSzqPMH4rOQZ6WHwtcqoKu', -- nosemgrep: generic.secrets.security.detected-bcrypt-hash.detected-bcrypt-hash
    'On-call Demo',
    true
)
ON CONFLICT (id) DO UPDATE SET password_hash = EXCLUDED.password_hash;

INSERT INTO user_roles (user_id, role)
VALUES ('6d0c5f5e-7f0f-4a4e-9d0c-1a1c1d3a7000', 'USER')
ON CONFLICT DO NOTHING;
