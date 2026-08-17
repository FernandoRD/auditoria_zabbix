# Usar uma imagem base oficial do Python
FROM python:3.11-slim

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
RUN python -c "import pypandoc; pypandoc.download_pandoc(targetfolder='/opt/pandoc', delete_installer=True)"
ENV PYPANDOC_PANDOC=/opt/pandoc/pandoc

# Copiar somente o conteúdo necessário em runtime; o contexto de build pode
# conter credenciais, evidências e relatórios locais.
COPY api ./api
COPY core ./core
COPY gui ./gui
COPY prompts ./prompts
COPY templates ./templates
COPY main.py __init__.py ./

# A aplicação de desktop não precisa rodar como root dentro do contêiner.
RUN groupadd --system app && \
    useradd --system --gid app --home-dir /app --shell /usr/sbin/nologin app && \
    chown -R app:app /app && \
    install -d --owner=app --group=app --mode=0700 /data /data/tmp && \
    install -d --mode=1777 /tmp/.X11-unix && \
    touch /tmp/.Xauthority
USER app

# Comando para iniciar a aplicação
CMD ["python", "/app/main.py"]
