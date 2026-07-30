-- A imagem pgvector/pgvector já traz a extensão compilada; aqui ela é habilitada no
-- banco da aplicação, na primeira inicialização do volume.
CREATE EXTENSION IF NOT EXISTS vector;
