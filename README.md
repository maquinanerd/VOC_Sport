# RSS AI Content Pipeline para Notícias de Economia e Política

Este é um aplicativo de produção em Python que automatiza o processo de leitura de feeds RSS de notícias sobre economia, política e investimentos, reescrevendo o conteúdo com IA e publicando no WordPress.

## Funcionalidades

- **Leitura de Feeds RSS**: Lê múltiplos feeds RSS em uma ordem pré-definida.
- **Extração de Conteúdo**: Extrai o artigo completo, incluindo título, conteúdo, imagens e vídeos do YouTube.
- **Reescrita com IA**: Utiliza um modelo de linguagem (Gemini) para reescrever e otimizar o conteúdo para SEO, seguindo um prompt customizável.
- **Publicação no WordPress**: Publica o artigo reescrito automaticamente via API REST, definindo título, conteúdo, resumo, categorias, tags e imagem destacada.
- **Agendamento**: Roda em ciclos contínuos usando `APScheduler`.
- **Resiliência**: Inclui retentativas com backoff exponencial, failover de chaves de API e deduplicação de artigos.
- **Armazenamento**: Usa um banco de dados SQLite para rastrear artigos processados e falhas.
- **Modularidade**: O código é organizado em módulos com responsabilidades claras.

## Arquitetura

O projeto é estruturado como um pacote Python `app/` com os seguintes módulos:

- `main.py`: Ponto de entrada, gerencia o agendador de tarefas.
- `config.py`: Centraliza a leitura de todas as configurações a partir de variáveis de ambiente.
- `feeds.py`: Responsável pela leitura e parsing dos feeds RSS.
- `extractor.py`: Baixa e extrai o conteúdo principal das páginas dos artigos.
- `ai_processor.py`: Interage com a API de IA para reescrever o conteúdo.
- `rewriter.py`: Valida e sanitiza a resposta da IA.
- `tags.py`: Extrai tags relevantes do conteúdo original.
- `categorizer.py`: Mapeia feeds para categorias do WordPress.
- `media.py`: Gerencia o download e upload de imagens.
- `wordpress.py`: Cliente para a API REST do WordPress.
- `store.py`: Gerencia o banco de dados SQLite.
- `logging_conf.py`: Configuração do sistema de logs.
- `cleanup.py`: Tarefa agendada para limpar dados antigos.

## Instalação

1.  **Clone o repositório:**
    ```bash
    git clone <url-do-repositorio>
    cd <nome-do-repositorio>
    ```

2.  **Crie e configure o arquivo de ambiente:**
    - Renomeie o arquivo `.env.example` para `.env`.
    - Abra o arquivo `.env` e preencha todas as variáveis com suas credenciais e configurações.

3.  **Instale as dependências:**
    Recomenda-se o uso de um ambiente virtual.
    ```bash
    make install
    ```
    Após a instalação, ative