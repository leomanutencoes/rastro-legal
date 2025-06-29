# app.py
import os
import re
import json
import shutil
import socket
import whois
import requests
import subprocess
import numpy as np
import face_recognition
from datetime import datetime
from flask import Flask, render_template, request, jsonify, send_file, after_this_request
from flask_cors import CORS
from bs4 import BeautifulSoup
from io import BytesIO
from PIL import Image
import pytesseract
import dns.resolver
import nmap
from sklearn.cluster import DBSCAN
from sklearn.preprocessing import StandardScaler
import torch
from transformers import pipeline, AutoTokenizer, AutoModelForQuestionAnswering
import openai
from dotenv import load_dotenv

# Carregar variáveis de ambiente
load_dotenv()

app = Flask(__name__)
CORS(app)
app.secret_key = 'rastro_legal_secreto_2023'

# Configurações de API
SHODAN_API_KEY = os.getenv('SHODAN_API_KEY', 'SUA_CHAVE_SHODAN')
VIRUSTOTAL_API_KEY = os.getenv('VIRUSTOTAL_API_KEY', 'SUA_CHAVE_VIRUSTOTAL')
ABUSEIPDB_API_KEY = os.getenv('ABUSEIPDB_API_KEY', 'SUA_CHAVE_ABUSEIPDB')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY', 'SUA_CHAVE_OPENAI')

# Configuração OpenAI
openai.api_key = OPENAI_API_KEY

# Configurações do sistema
UPLOAD_FOLDER = 'uploads'
KNOWN_FACES_FOLDER = 'known_faces'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(KNOWN_FACES_FOLDER, exist_ok=True)

# Carregar modelos de IA
try:
    # Modelo para análise de texto e NER (Reconhecimento de Entidades Nomeadas)
    nlp_ner = pipeline("ner", model="neuralmind/bert-base-portuguese-cased", aggregation_strategy="simple")
    
    # Modelo para análise de sentimento em português
    sentiment_analyzer = pipeline("sentiment-analysis", model="nlptown/bert-base-multilingual-uncased-sentiment")
    
    # Modelo para Q&A (Pergunta e Resposta)
    qa_tokenizer = AutoTokenizer.from_pretrained("pierreguillou/bert-base-cased-squad-v1.1-portuguese")
    qa_model = AutoModelForQuestionAnswering.from_pretrained("pierreguillou/bert-base-cased-squad-v1.1-portuguese")
    qa_pipeline = pipeline("question-answering", model=qa_model, tokenizer=qa_tokenizer)
    
    print("Modelos de IA carregados com sucesso!")
except Exception as e:
    print(f"Erro ao carregar modelos de IA: {str(e)}")
    nlp_ner = None
    sentiment_analyzer = None
    qa_pipeline = None

# ... (código anterior para ferramentas, monitored_items e funções de investigação) ...

# ==============================
# MÓDULO AVANÇADO DE IA
# ==============================

class IAInvestigation:
    def __init__(self):
        self.known_faces = self.load_known_faces()
    
    def load_known_faces(self):
        """Carrega rostos conhecidos do diretório de faces conhecidas"""
        known_faces = {}
        for filename in os.listdir(KNOWN_FACES_FOLDER):
            if filename.lower().endswith(('.png', '.jpg', '.jpeg')):
                path = os.path.join(KNOWN_FACES_FOLDER, filename)
                image = face_recognition.load_image_file(path)
                encodings = face_recognition.face_encodings(image)
                if encodings:
                    # Usar o nome do arquivo (sem extensão) como identificador
                    person_id = os.path.splitext(filename)[0]
                    known_faces[person_id] = encodings[0]
        return known_faces
    
    def add_known_face(self, image_path, person_id):
        """Adiciona um novo rosto conhecido ao sistema"""
        try:
            image = face_recognition.load_image_file(image_path)
            encodings = face_recognition.face_encodings(image)
            if encodings:
                self.known_faces[person_id] = encodings[0]
                # Salvar a imagem no diretório de faces conhecidas
                output_path = os.path.join(KNOWN_FACES_FOLDER, f"{person_id}.jpg")
                Image.open(image_path).save(output_path)
                return True
            return False
        except Exception as e:
            print(f"Erro ao adicionar rosto conhecido: {str(e)}")
            return False
    
    def recognize_faces(self, image_path):
        """Reconhece rostos em uma imagem e compara com rostos conhecidos"""
        try:
            # Carregar a imagem
            unknown_image = face_recognition.load_image_file(image_path)
            
            # Encontrar todos os rostos na imagem
            face_locations = face_recognition.face_locations(unknown_image)
            face_encodings = face_recognition.face_encodings(unknown_image, face_locations)
            
            recognized = []
            for i, face_encoding in enumerate(face_encodings):
                # Comparar com rostos conhecidos
                matches = face_recognition.compare_faces(
                    list(self.known_faces.values()), 
                    face_encoding
                )
                
                name = "Desconhecido"
                confidence = 0.0
                
                # Calcular distâncias
                face_distances = face_recognition.face_distance(
                    list(self.known_faces.values()), 
                    face_encoding
                )
                
                # Encontrar a melhor correspondência
                best_match_index = np.argmin(face_distances)
                if matches[best_match_index]:
                    name = list(self.known_faces.keys())[best_match_index]
                    confidence = 1 - face_distances[best_match_index]
                
                recognized.append({
                    "location": face_locations[i],
                    "name": name,
                    "confidence": round(confidence, 2)
                })
            
            return recognized
        except Exception as e:
            print(f"Erro no reconhecimento facial: {str(e)}")
            return []
    
    def analyze_text(self, text):
        """Analisa texto usando NLP para extrair informações relevantes"""
        if not nlp_ner:
            return {"error": "Modelo NLP não disponível"}
        
        try:
            # Extrair entidades nomeadas
            entities = nlp_ner(text)
            
            # Analisar sentimento
            sentiment = sentiment_analyzer(text)[0] if sentiment_analyzer else None
            
            # Classificar entidades
            people = [e['word'] for e in entities if e['entity_group'] == 'PER']
            locations = [e['word'] for e in entities if e['entity_group'] == 'LOC']
            organizations = [e['word'] for e in entities if e['entity_group'] == 'ORG']
            dates = [e['word'] for e in entities if e['entity_group'] == 'DATE']
            
            return {
                "entities": entities,
                "sentiment": sentiment,
                "people": list(set(people)),
                "locations": list(set(locations)),
                "organizations": list(set(organizations)),
                "dates": list(set(dates))
            }
        except Exception as e:
            return {"error": str(e)}
    
    def answer_question(self, context, question):
        """Responde perguntas baseadas em um contexto"""
        if not qa_pipeline:
            return {"error": "Modelo Q&A não disponível"}
        
        try:
            result = qa_pipeline(question=question, context=context)
            return {
                "answer": result['answer'],
                "score": result['score'],
                "start": result['start'],
                "end": result['end']
            }
        except Exception as e:
            return {"error": str(e)}
    
    def generate_investigation_hypotheses(self, evidence):
        """Gera hipóteses de investigação usando IA generativa"""
        if not OPENAI_API_KEY or OPENAI_API_KEY == 'SUA_CHAVE_OPENAI':
            return {"error": "Chave da API OpenAI não configurada"}
        
        try:
            prompt = f"""
            Com base nas seguintes evidências de investigação, gere hipóteses sobre o paradeiro e atividades do indivíduo investigado.
            Forneça também sugestões para próximos passos na investigação.

            Evidências:
            {json.dumps(evidence, indent=2)}

            Hipóteses e Recomendações:
            """
            
            response = openai.Completion.create(
                engine="text-davinci-003",
                prompt=prompt,
                max_tokens=500,
                temperature=0.7,
                top_p=1.0,
                frequency_penalty=0.0,
                presence_penalty=0.0
            )
            
            return response.choices[0].text.strip()
        except Exception as e:
            return {"error": str(e)}
    
    def correlate_entities(self, entities_list):
        """Correlaciona entidades de diferentes fontes usando clusterização"""
        try:
            # Criar uma lista única de todas as entidades
            all_entities = []
            for entities in entities_list:
                all_entities.extend(entities)
            
            # Converter para conjunto para remover duplicatas
            unique_entities = list(set(all_entities))
            
            # Criar matriz de similaridade (simplificada)
            # Em implementação real, usar embeddings de texto
            entity_matrix = np.zeros((len(unique_entities), dtype=int)
            
            # Clusterização DBSCAN (exemplo simplificado)
            # Em implementação real, usar embeddings mais sofisticados
            X = StandardScaler().fit_transform(entity_matrix.reshape(-1, 1))
            clustering = DBSCAN(eps=0.5, min_samples=2).fit(X)
            
            # Agrupar entidades por cluster
            clusters = {}
            for i, label in enumerate(clustering.labels_):
                if label not in clusters:
                    clusters[label] = []
                clusters[label].append(unique_entities[i])
            
            return clusters
        except Exception as e:
            return {"error": str(e)}
    
    def analyze_social_connections(self, social_data):
        """Analisa conexões sociais para identificar relacionamentos-chave"""
        try:
            # Estrutura para armazenar conexões
            connections = {}
            
            # Simulação de análise - em produção seria mais complexo
            for platform, data in social_data.items():
                if 'connections' in data:
                    for connection in data['connections']:
                        name = connection.get('name', '')
                        relation = connection.get('relation', '')
                        
                        if name not in connections:
                            connections[name] = {
                                'relations': set(),
                                'platforms': set(),
                                'occurrences': 0
                            }
                        
                        connections[name]['relations'].add(relation)
                        connections[name]['platforms'].add(platform)
                        connections[name]['occurrences'] += 1
            
            # Converter sets para lists para serialização
            for name, data in connections.items():
                data['relations'] = list(data['relations'])
                data['platforms'] = list(data['platforms'])
            
            # Identificar conexões mais relevantes
            sorted_connections = sorted(
                connections.items(), 
                key=lambda x: x[1]['occurrences'], 
                reverse=True
            )
            
            return {
                'all_connections': connections,
                'top_connections': sorted_connections[:5]  # Top 5 conexões
            }
        except Exception as e:
            return {"error": str(e)}

# Inicializar o módulo de IA
ia_system = IAInvestigation()

# ==============================
# ROTAS DE IA
# ==============================

@app.route('/ia/recognize_faces', methods=['POST'])
def ia_recognize_faces():
    """Reconhece rostos em uma imagem enviada"""
    if 'file' not in request.files:
        return jsonify({"status": "error", "message": "Nenhum arquivo enviado"})
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({"status": "error", "message": "Nome de arquivo vazio"})
    
    file_path = os.path.join(UPLOAD_FOLDER, file.filename)
    file.save(file_path)
    
    # Reconhecer rostos
    recognized_faces = ia_system.recognize_faces(file_path)
    
    # Remover arquivo após análise
    @after_this_request
    def remove_file(response):
        try:
            os.remove(file_path)
        except Exception as e:
            app.logger.error(f"Erro ao remover arquivo: {str(e)}")
        return response
    
    return jsonify({"status": "success", "results": recognized_faces})

@app.route('/ia/add_known_face', methods=['POST'])
def ia_add_known_face():
    """Adiciona um novo rosto conhecido ao sistema"""
    if 'file' not in request.files:
        return jsonify({"status": "error", "message": "Nenhum arquivo enviado"})
    
    file = request.files['file']
    person_id = request.form.get('person_id', '')
    
    if not person_id:
        return jsonify({"status": "error", "message": "ID da pessoa não fornecido"})
    
    if file.filename == '':
        return jsonify({"status": "error", "message": "Nome de arquivo vazio"})
    
    file_path = os.path.join(UPLOAD_FOLDER, file.filename)
    file.save(file_path)
    
    # Adicionar rosto conhecido
    success = ia_system.add_known_face(file_path, person_id)
    
    # Remover arquivo temporário
    try:
        os.remove(file_path)
    except Exception as e:
        app.logger.error(f"Erro ao remover arquivo: {str(e)}")
    
    if success:
        return jsonify({"status": "success", "message": "Rosto adicionado com sucesso"})
    else:
        return jsonify({"status": "error", "message": "Não foi possível adicionar o rosto"})

@app.route('/ia/analyze_text', methods=['POST'])
def ia_analyze_text():
    """Analisa texto usando NLP"""
    data = request.json
    text = data.get('text', '')
    
    if not text:
        return jsonify({"status": "error", "message": "Texto vazio"}), 400
    
    analysis = ia_system.analyze_text(text)
    return jsonify({"status": "success", "results": analysis})

@app.route('/ia/generate_hypotheses', methods=['POST'])
def ia_generate_hypotheses():
    """Gera hipóteses de investigação com base em evidências"""
    data = request.json
    evidence = data.get('evidence', {})
    
    if not evidence:
        return jsonify({"status": "error", "message": "Nenhuma evidência fornecida"}), 400
    
    hypotheses = ia_system.generate_investigation_hypotheses(evidence)
    return jsonify({"status": "success", "results": hypotheses})

@app.route('/ia/answer_question', methods=['POST'])
def ia_answer_question():
    """Responde perguntas com base em um contexto"""
    data = request.json
    context = data.get('context', '')
    question = data.get('question', '')
    
    if not context or not question:
        return jsonify({"status": "error", "message": "Contexto ou pergunta ausentes"}), 400
    
    answer = ia_system.answer_question(context, question)
    return jsonify({"status": "success", "results": answer})

@app.route('/ia/correlate_entities', methods=['POST'])
def ia_correlate_entities():
    """Correlaciona entidades de diferentes fontes"""
    data = request.json
    entities_list = data.get('entities_list', [])
    
    if not entities_list:
        return jsonify({"status": "error", "message": "Lista de entidades vazia"}), 400
    
    clusters = ia_system.correlate_entities(entities_list)
    return jsonify({"status": "success", "results": clusters})

@app.route('/ia/analyze_social_connections', methods=['POST'])
def ia_analyze_social_connections():
    """Analisa conexões sociais para identificar relacionamentos-chave"""
    data = request.json
    social_data = data.get('social_data', {})
    
    if not social_data:
        return jsonify({"status": "error", "message": "Dados sociais ausentes"}), 400
    
    analysis = ia_system.analyze_social_connections(social_data)
    return jsonify({"status": "success", "results": analysis})

# ... (rotas existentes) ...

if __name__ == '__main__':
    # ... (código de verificação de ferramentas) ...
    
    # Iniciar servidor
    app.run(host='0.0.0.0', port=5000, debug=True)
