# Usar uma imagem base oficial do Python
FROM python:3.10-slim

# Evitar que o Python grave arquivos .pyc e forçar logs no console
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Atualizar pacotes e instalar dependências de sistema
# - python3-tk e tk-dev: Necessários para renderizar a interface gráfica Tkinter
# - dependências extras para garantir o correto funcionamento do sistema
RUN apt-get update && apt-get install -y \
    python3-tk \
    tk-dev \
    wget \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Definir o diretório de trabalho
WORKDIR /app

# Copiar o arquivo de dependências primeiro para aproveitar o cache do Docker
COPY requirements.txt .

# Instalar as dependências do Python (inclui matplotlib e typst, sem dependências de sistema extras)
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Baixar o binário do Pandoc (>= 3.1.7, necessário para o writer Typst) via pypandoc,
# em vez do pacote "pandoc" do apt (Debian slim traz uma versão 2.x sem suporte a Typst)
RUN python -c "import pypandoc; pypandoc.download_pandoc()"

# CACHE BUST START (Não fazer cache daqui em diante)
ARG CACHEBUST=1 
# Copiar o restante do código da aplicação
COPY . .

# Comando para iniciar a aplicação
CMD ["python", "main.py"]