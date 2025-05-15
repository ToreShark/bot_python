
import bs4
from dotenv import load_dotenv
from langchain import hub
from operator import itemgetter
from langchain_community.document_loaders import WebBaseLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
import os
from langchain_community.document_loaders import TextLoader
from langchain_core.documents import Document
from langchain.load import dumps, loads
from langchain_anthropic import ChatAnthropic


from langchain_community.vectorstores import Chroma
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from utils import format_qa_pair, format_qa_pairs

from colorama import Fore
import warnings
import os
import hashlib

warnings.filterwarnings("ignore")

load_dotenv()

# LLM
# llm = ChatOpenAI(model="gpt-4-turbo")
llm = ChatAnthropic(
    model="claude-3-5-sonnet-20241022",  # Можно использовать другую модель, например claude-3-7-sonnet-latest
    temperature=0.2,
    max_tokens=4000,
    # Не используем anthropic_api_key, поскольку библиотека сама возьмет ключ из переменных окружения
)

# # 1. Load legal documents
# docs = []
# for filename in os.listdir("docs"):
#     if filename.endswith(".txt"):
#         loader = TextLoader(os.path.join("docs", filename), encoding='utf-8')
#         docs.extend(loader.load())

docs_path = "./docs"  # путь к папке с документами
docs = []

for filename in os.listdir(docs_path):
    if filename.endswith(".txt"):
        with open(os.path.join(docs_path, filename), "r", encoding="utf-8") as f:
            content = f.read()
            docs.append(Document(page_content=content, metadata={"source": filename}))
            # print(Fore.YELLOW + f"[LOG] Загружен документ: {filename}" + Fore.RESET)



# 2. Split into chunks
text_splitter = RecursiveCharacterTextSplitter.from_tiktoken_encoder(
    chunk_size=500,
    chunk_overlap=50
)
splits = text_splitter.split_documents(docs)
# print(Fore.YELLOW + f"[LOG] Всего фрагментов после разбиения: {len(splits)}" + Fore.RESET)
for s in splits[:3]:
    print(Fore.LIGHTBLACK_EX + s.page_content[:200] + "..." + Fore.RESET)


# 3. Create vectorstore
# # Пути для хранения
persist_directory = "./chroma_db"
hash_file = "./docs_hash.txt"

# Функция для вычисления хеша документов
def get_documents_hash(documents):
    """Создает хеш-сумму для всех документов"""
    content = "".join([doc.page_content for doc in documents])
    return hashlib.md5(content.encode()).hexdigest()

# Получаем текущий хеш документов
current_hash = get_documents_hash(splits)

# Проверяем, нужно ли обновлять embeddings
need_update = True
if os.path.exists(hash_file):
    with open(hash_file, "r") as f:
        stored_hash = f.read().strip()
    
    # Если хеш не изменился, обновление не требуется
    if current_hash == stored_hash and os.path.exists(persist_directory):
        need_update = False
        print(Fore.GREEN + f"[LOG] Документы не изменились, используем существующие embeddings" + Fore.RESET)

# Создаем или загружаем векторное хранилище
if need_update:
    print(Fore.YELLOW + f"[LOG] Документы изменились или хранилище не существует. Создаем новые embeddings..." + Fore.RESET)
    
    # Создаем embeddings и сохраняем в Chroma
    vectorstore = Chroma.from_documents(
        documents=splits, 
        embedding=OpenAIEmbeddings(model="text-embedding-3-large"),
        persist_directory=persist_directory
    )
    
    # Сохраняем векторное хранилище и хеш
    vectorstore.persist()
    with open(hash_file, "w") as f:
        f.write(current_hash)
    
    print(Fore.GREEN + f"[LOG] Создано новое векторное хранилище в {persist_directory}" + Fore.RESET)
else:
    # Загружаем существующее хранилище
    embedding_function = OpenAIEmbeddings(model="text-embedding-3-large")
    vectorstore = Chroma(
        persist_directory=persist_directory, 
        embedding_function=embedding_function
    )
    print(Fore.GREEN + f"[LOG] Загружено существующее векторное хранилище из {persist_directory}" + Fore.RESET)

# Создаем retriever как обычно
retriever = vectorstore.as_retriever()

# 1. DECOMPOSITION
# template = """Вы эксперт по банкротству в Казахстане. 
#     Клиент задал вопрос: {question}
    
#     Сгенерируйте 3 поисковых подвопроса для поиска в базе знаний, которые:
#     1. Найдут релевантные процедуры банкротства
#     2. Найдут конкретные решения для запроса клиента
#     3. Найдут условия применения этих процедур
    
#     Подвопросы должны быть ориентированы на поиск в документах, а не на диалог с клиентом.
#     Выведите только сами вопросы (3 штуки)."""
template = """Вы юридический помощник по банкротству физических лиц в Казахстане.
Пользователь задал вопрос: {question}

Сформулируйте 3 юридически точных подвопроса для поиска в базе знаний, которые строго ссылаются на Закон Республики Казахстан "О восстановлении платежеспособности и банкротстве граждан Республики Казахстан" (с изменениями и дополнениями от 20.08.2024 г.).

Цель:
1. Найти применимую процедуру (внесудебное банкротство, судебное банкротство или восстановление платежеспособности).
2. Уточнить условия, ограничения и требования применения этих процедур.
3. Получить алгоритм действий, основанный на положениях указанного закона.

⚖️ Обязательно:
- Используйте юридический язык.
- Ссылайтесь на конкретные статьи Закона РК "О восстановлении платежеспособности и банкротстве граждан Республики Казахстан" (в ред. от 20.08.2024 г.), если это возможно.
- Не упоминайте другие законы или нормативные акты.
- Не ведите диалог — цель: получить знания из нормативной документации, а не вести беседу.
"""
# template = """Сформулируй 5 переформулированных версий следующего юридического запроса для поиска в базе знаний:

# {question}

# Формулируй как юрист, используй разные формулировки одного смысла, каждую с новой строки."""

prompt_decomposition = ChatPromptTemplate.from_template(template)

def generate_multi_queries_for_subquestion(question):
    """Создаёт 5 формулировок одного подвопроса"""
    chain = prompt_decomposition | llm | StrOutputParser() | (lambda x: x.split("\n"))
    return chain.invoke({"question": question})

def get_unique_union(documents: list[list]):
    """Объединить списки документов и удалить дубликаты"""
    flattened = [dumps(doc) for sublist in documents for doc in sublist]
    unique_docs = list(set(flattened))
    return [loads(doc) for doc in unique_docs]

def retrieve_documents(sub_questions):
    """Для каждого подвопроса → 5 формулировок → поиск → объединение"""
    all_retrieved_docs = {}

    for sub_q in sub_questions:
        # print(Fore.BLUE + f"[LOG] Запрос: {sub_q}" + Fore.RESET)
        multi_qs = generate_multi_queries_for_subquestion(sub_q)

        doc_lists = []
        for q in multi_qs:
            docs_found = retriever.get_relevant_documents(q)
            # print(Fore.LIGHTMAGENTA_EX + f"[RETRIEVER] Запрос: {q} — Найдено документов: {len(docs_found)}" + Fore.RESET)
            for d in docs_found[:1]:
                # print(Fore.LIGHTCYAN_EX + f"Фрагмент: {d.page_content[:100]}..." + Fore.RESET)
                 pass  # или оставь print, если нужно временно
            doc_lists.append(docs_found)
        
        unique_docs = get_unique_union(doc_lists)
        all_retrieved_docs[sub_q] = unique_docs  # 🔥 Вставь это!
        # print(Fore.YELLOW + f"[LOG] Уникальных документов для подвопроса: {len(unique_docs)}" + Fore.RESET)

    return all_retrieved_docs


def generate_sub_questions(query):
    """ generate sub questions based on user query"""
    pass 
    # Chain
    generate_queries_decomposition = (
        prompt_decomposition 
        | llm 
        | StrOutputParser()
        | (lambda x: x.split("\n"))
    ) 

    # Run
    sub_questions = generate_queries_decomposition.invoke({"question": query})
    questions_str = "\n".join(sub_questions)
    # print(Fore.MAGENTA + "=====  ПОИСКОВЫЕ ПОДВОПРОСЫ: =====" + Fore.RESET)
    # print(Fore.WHITE + questions_str + Fore.RESET + "\n")
    return sub_questions 
      

# 2. ANSWER SUBQUESTIONS RECURSIVELY 
template = """Вот вопрос, на который нужно ответить:

\n --- \n {sub_question} \n --- \n

Ниже приведены пары предыдущих вопросов и ответов, если они имеются:

\n --- \n {q_a_pairs} \n --- \n

Контекст, извлечённый из базы знаний:

\n --- \n {context} \n --- \n

Используя приведённый контекст и пары вопрос-ответ, дайте развернутый, точный и юридически обоснованный ответ на вопрос: \n {sub_question}

Пиши на русском языке. Если в контексте указана статья закона, обязательно ссылайся на неё.
"""

prompt_qa = ChatPromptTemplate.from_template(template)


def generate_qa_pairs(retrieved_docs_dict):
    q_a_pairs = ""

    for sub_question, context_docs in retrieved_docs_dict.items():
        context = "\n".join([doc.page_content for doc in context_docs])

        inputs = {
            "sub_question": sub_question,
            "q_a_pairs": q_a_pairs,
            "context": context
        }

        generate_qa = prompt_qa | llm | StrOutputParser()
        # print(Fore.LIGHTYELLOW_EX + "[CONTEXT] " + context[:500] + "..." + Fore.RESET)
        answer = generate_qa.invoke(inputs)
       

        # Форматировать результат
        q_a_pair = format_qa_pair(sub_question, answer)
        q_a_pairs += "\n --- \n" + q_a_pair

        # print(Fore.GREEN + f"=====  Q/A PAIR: =====" + Fore.RESET)
        # print(Fore.CYAN + f"Q: {sub_question}\nA: {answer}" + Fore.RESET + "\n")

    return q_a_pairs
        

# 3. ANSWER INDIVIDUALY

# RAG prompt = https://smith.langchain.com/hub/rlm/rag-prompt
prompt_rag = hub.pull("rlm/rag-prompt")


def retrieve_and_rag(prompt_rag, sub_questions):
    """RAG on each sub-question"""
    rag_results = []
    for sub_question in sub_questions:
        retrieved_docs = retriever.get_relevant_documents(sub_question)

        answer_chain = (
            prompt_rag
            | llm
            | StrOutputParser()
        )
        answer = answer_chain.invoke({"question": sub_question, "context": retrieved_docs})
        rag_results.append(answer)
    
    return rag_results, sub_questions
    
# SUMMARIZE AND ANSWER 

# Prompt
template = """Вот набор пар вопрос-ответ из базы знаний:

{context}

На основе этих данных, пожалуйста, сформируй финальный ответ на вопрос пользователя: {question}

Постарайся сделать ответ как можно более полным и точным. Если не знаешь ответа, просто скажи "не знаю".
Если вопрос не относится к банкротству, просто скажи "не знаю".
Давай ответ как профессионал, но не используй сложные термины.
Пример начала:  
"Согласно ст. 6 Закона РК "О восстановлении платежеспособности и банкротстве граждан Республики Казахстан", если у должника нет 12 месяцев просрочек, применяется процедура восстановления платежеспособности..."  

⚖️ Обязательно:
- Приводи ссылки на статьи закона, если информация указана в контексте. Например: "ст. 6 Закона РК о банкротстве".
- Не используй обтекаемые фразы ("можно использовать стратегию", "в зависимости от ситуации").
- Отвечай конкретно: "Да, это основание для отказа" или "Нет, закон этого не требует".
"""

prompt = ChatPromptTemplate.from_template(template)


def query(query_text, progress_callback=lambda x: None):
    # Шаг 1: генерация подвопросов
    progress_callback("🔍 Генерирую юридические подвопросы...")
    sub_questions = generate_sub_questions(query_text)

    # Шаг 2: поиск документов
    progress_callback("📚 Ищу релевантные документы...")
    retrieved_docs_dict = retrieve_documents(sub_questions)

    # Шаг 3: генерация Q/A по документам
    progress_callback("⚖️ Анализирую законодательство и судебную практику...")
    q_a_pairs = generate_qa_pairs(retrieved_docs_dict)

    # Шаг 4: итоговый ответ
    progress_callback("🧠 Формирую итоговый юридический вывод...")
    final_rag_chain = (
        prompt
        | llm
        | StrOutputParser()
    )

    return final_rag_chain.invoke({"question": query_text, "context": q_a_pairs})