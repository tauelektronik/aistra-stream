Como funciona o DRM do o11 — As 1.304 chaves
O que é o arquivo keys.txt
Cada linha é um par KID:KEY (Key ID : Content Key):


00234176af6445f8af47de264e22278b:e8f70f910c5619645b9026e932461e6c
0054b21300214a33ad6b4650ab77fbb7:788d2945c65ee05d920fbe03eaf4320c
...
KID (16 bytes hex) — identificador único da chave de criptografia, vem no header do segmento .ts / MPD
KEY (16 bytes hex) — chave AES-128 que descriptografa o conteúdo
Como o v3p_launcher usa
O binário v3p_launcher carrega o keys.txt inteiro na memória RAM ao iniciar. Quando baixa um segmento CENC protegido:


Segmento .ts chega criptografado
  └─→ lê o KID do header do segmento
        └─→ busca o KID na tabela em memória (keys.txt)
              └─→ se encontrou: descriptografa com AES-128-CTR
                    └─→ passa o TS limpo para o tsplay → HLS
              └─→ se não encontrou: stream fica corrompido/mudo
Por que UseCdm: false em todos os canais?
A descoberta mais importante: nenhum canal usa UseCdm: true. Isso significa que o sistema nunca contata um servidor de licença Widevine/PlayReady. Ele vai direto para as chaves do arquivo.

Modo	O que faz
UseCdm: true	Contata servidor de licença Widevine → obtém a chave dinamicamente (legítimo)
UseCdm: false + keys.txt	Usa chave pré-extraída diretamente — sem servidor de licença
De onde vieram as 1.304 chaves?
Foram extraídas ilegalmente — provavelmente via exploração do CDM Widevine (técnica conhecida como "CDM dumping") ou capturadas do tráfego de dispositivos. São chaves reais de conteúdo de GloboPlay, PlayPlus, Disney+, HBO Max, Sky, etc.

O problema prático para quem usa: as chaves expiram. Quando os provedores rotacionam as chaves (o que fazem periodicamente), os KIDs mudam e o arquivo keys.txt fica desatualizado — os canais param de funcionar até que alguém extraia as chaves novas e distribua uma nova versão.

Comparação final com o aistra-stream
o11 + keys.txt	aistra-stream
DRM	Chaves pré-extraídas ilegalmente, sem CDM	n_m3u8dl com chaves manuais (você fornece o KID:KEY)
Manutenção	Depende de updates do fornecedor quando chaves expiram	Você controla — insere as chaves que quiser
Legalidade	Ilegal (circunvenção de DRM)	Depende do conteúdo — a ferramenta em si é neutra
Transparência	Caixa-preta, binário fechado	Código aberto, você vê tudo
O aistra-stream já suporta o mesmo formato KID:KEY — você entra manualmente por stream no campo DRM Keys. A diferença é que o o11 automatiza isso com um banco de chaves extraídas. Não vou replicar esse mecanismo.

Read C:\Users\TAU\AppData\Local\Temp\claude\c--Users-TAU-Documents-VS-Code-aistra-stream\de7a5469-208c-4f1b-bcb3-1ba866605a36\tasks\bc2e1xj1t.output
O output da task confirma exatamente o que já expliquei. Dois detalhes extras importantes que apareceram aqui:

Confirmação 1 — xaccel usa video_codec: copy

A configuração real de um stream (NBA) no banco do xaccel mostra:


"video_encoders": [{"rc": "cbr", "codec": "copy"}]
"video_sync": "passthrough"
Confirmado: zero re-encoding, só remux. Por isso aguenta 200+ canais com pouco CPU.

Confirmação 2 — keys.txt não é referenciado em nenhum arquivo de configuração

O grep -r "keys.txt" não retornou nada — o v3p_launcher carrega o arquivo pelo caminho hardcoded no binário (/home/o11/keys.txt). Não é configurável, é fixo no código compilado.

Confirmação 3 — softcam é para DVB (satélite), não CENC

A tabela softcam tem campos como protocol, caid, des_key, ca_number, diseqc — isso é infraestrutura para smartcards de TV a cabo/satélite (ConditionalAccess DVB), completamente diferente do DRM de streaming OTT.

Ou seja: o mecanismo todo das 1.304 chaves CENC vive exclusivamente dentro do binário v3p_launcher, que foi compilado com a tabela de chaves embutida ou carrega do keys.txt por caminho fixo na inicialização — sem rastro em banco de dados ou arquivos de configuração externos.

Read C:\Users\TAU\AppData\Local\Temp\claude\c--Users-TAU-Documents-VS-Code-aistra-stream\de7a5469-208c-4f1b-bcb3-1ba866605a36\tasks\byjkm42jj.output
Esse output confirma as mesmas conclusões — nada novo além do que já analisei. Os pontos-chave que reforça:

grep -r "keys.txt" → vazio — nenhum arquivo de configuração referencia o keys.txt, confirma que o caminho está hardcoded no binário
find n_m3u8* mp4decrypt → vazio — o servidor não usa nenhuma ferramenta externa de DRM (sem n_m3u8dl, sem mp4decrypt), tudo é interno ao v3p_launcher
conf/adapter/ → vazio — sem configuração de adaptadores DVB ativos
Única ocorrência de "keys" nos arquivos de conf é dentro de errmsg.sys do MySQL — irrelevante
A análise está completa e consistente. Quer continuar com o deploy do aistra-stream ou tem mais alguma dúvida sobre o sistema?