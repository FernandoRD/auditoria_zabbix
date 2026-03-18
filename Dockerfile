# Usar uma imagem base oficial do Python
FROM python:3.10-slim

# Evitar que o Python grave arquivos .pyc e forçar logs no console
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Atualizar pacotes e instalar dependências de sistema
# - python3-tk e tk-dev: Necessários para renderizar a interface gráfica Tkinter
# - pandoc: Necessário para o pypandoc exportar os relatórios
# - dependências extras para garantir o correto funcionamento do sistema
RUN apt-get update && apt-get install -y \
    python3-tk \
    tk-dev \
    pandoc \
    wget \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Definir o diretório de trabalho
WORKDIR /app

# Copiar o arquivo de dependências primeiro para aproveitar o cache do Docker
COPY requirements.txt .

# Instalar as dependências do Python
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Instalar o Playwright e executar a instalação dos navegadores com dependências do sistema
RUN pip install playwright && \
    playwright install --with-deps chromium

# Copiar o restante do código da aplicação
COPY . .

# Comando para iniciar a aplicação
CMD ["python", "main.py"]