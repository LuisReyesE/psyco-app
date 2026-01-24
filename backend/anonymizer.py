"""
Anonymizer Module for Session AI
---------------------------------
Provides text anonymization using spaCy NER and Gemini API integration.
The anonymization flow ensures no PII (Personally Identifiable Information) 
is sent to cloud services.

Flow:
1. Transcription text → SessionAnonymizer.anonymize() → Anonymized text
2. Anonymized text → GeminiProcessor.generate_clinical_note() → Anonymized response
3. Anonymized response → SessionAnonymizer.deanonymize() → Final response with real data
"""

import os
import re
import json
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


class SessionAnonymizer:
    """
    Anonymizes sensitive data in clinical conversation transcripts.
    Uses spaCy NER for entity detection and regex patterns for structured data.
    """
    
    _nlp = None  # Class-level model cache (lazy loading)
    
    def __init__(self):
        self.secret_map = {}
        self.reverse_map = {}
        self.counters = {
            'PER': 0, 'LOC': 0, 'ORG': 0,
            'DNI': 0, 'TEL': 0, 'EMAIL': 0, 'FECHA': 0, 'DIR': 0,
        }
        
        # Common false positives to ignore
        self.false_positives = {
            "haría", "pensé", "sentí", "suspira", "creí", "quería", "sabía",
            "tendría", "podría", "diría", "sería", "estaría", "vendría",
            "hice", "dije", "vine", "puse", "tuve", "supe", "quise",
            "dr", "dr.", "psicólogo", "paciente", "metro", "metro.",
        }
        
        self.speaker_names = set()
    
    @classmethod
    def get_nlp(cls):
        """Lazy load spaCy model (only when first needed)"""
        if cls._nlp is None:
            import spacy
            print("[NLP] Cargando modelo de espanol (es_core_news_lg)...")
            cls._nlp = spacy.load("es_core_news_lg")
            print("[OK] Modelo spaCy cargado correctamente!")
        return cls._nlp

    def get_or_create_placeholder(self, text: str, label: str) -> str:
        """Get existing placeholder or create a new one for the given text"""
        text_normalized = text.strip()
        key = (text_normalized, label)
        
        if key in self.reverse_map:
            return self.reverse_map[key]
        
        self.counters[label] += 1
        placeholder = f"[{label}_{self.counters[label]}]"
        self.secret_map[placeholder] = text_normalized
        self.reverse_map[key] = placeholder
        return placeholder

    def extract_speaker_names(self, text: str) -> set:
        """Extract names used as speakers (format: 'Name: dialogue')"""
        pattern = r'^([A-ZÁÉÍÓÚÑ][a-záéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+)*)\s*:'
        speakers = set()
        for line in text.split('\n'):
            match = re.match(pattern, line.strip())
            if match:
                speaker = match.group(1)
                if speaker.lower() not in ['psicólogo', 'paciente', 'doctor', 'terapeuta']:
                    speakers.add(speaker)
        self.speaker_names = speakers
        return speakers

    def extract_mentioned_names(self, text: str) -> set:
        """Extract names mentioned in greetings and relational contexts"""
        mentioned_names = set()
        patterns = [
            r'(?:Hola|Buenos días|Buenas tardes|Buenas noches|Bienvenido|Bienvenida),?\s+([A-ZÁÉÍÓÚÑ][a-záéíóúñ]+)',
            r'(?:señor|señora|don|doña|sr\.|sra\.)\s+([A-ZÁÉÍÓÚÑ][a-záéíóúñ]+)',
            r'(?:mi|tu|su|nuestro|nuestra)\s+(?:amigo|amiga|hermano|hermana|esposo|esposa|hijo|hija|padre|madre|colega|compañero|compañera)\s+([A-ZÁÉÍÓÚÑ][a-záéíóúñ]+)',
        ]
        for pattern in patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                name = match.group(1)
                if name.lower() not in self.false_positives and len(name) > 2:
                    mentioned_names.add(name)
        return mentioned_names

    def extract_sensitive_data(self, text: str) -> list:
        """Extract structured sensitive data using regex patterns"""
        sensitive_data = []
        patterns = {
            'DNI': [
                r'\b(\d{8})\b',
                r'(?:DNI|D\.N\.I\.|documento|identidad)[:\s]*(\d{8})\b',
            ],
            'TEL': [
                r'\b(9\d{8})\b',
                r'(\+51\s*9\d{8})',
                r'(\(\d{2,3}\)\s*\d{6,8})',
                r'(\d{2,3}[\-\s]\d{6,8})',
                r'(?:teléfono|celular|móvil|tel\.?|cel\.?|llamar? al|consultorio al)[:\s]*(\(?\d{2,3}\)?\s*[\-\s]?\d{6,9})',
            ],
            'EMAIL': [
                r'\b([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})\b',
            ],
            'FECHA': [
                r'\b(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4})\b',
                r'\b(\d{1,2}\s+de\s+(?:enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre)\s+(?:de\s+)?\d{2,4})\b',
            ],
            'DIR': [
                r'(?:calle|av\.|avenida|jr\.|jirón|psje\.|pasaje)\s+([A-Za-záéíóúñÁÉÍÓÚÑ\s]+\d+[A-Za-z\s,\-]*)',
            ],
        }
        
        for data_type, pattern_list in patterns.items():
            for pattern in pattern_list:
                for match in re.finditer(pattern, text, re.IGNORECASE):
                    value = match.group(1) if match.lastindex else match.group(0)
                    if len(value.strip()) >= 4:
                        sensitive_data.append({
                            'text': value.strip(),
                            'start': match.start(1) if match.lastindex else match.start(),
                            'end': match.end(1) if match.lastindex else match.end(),
                            'label': data_type
                        })
        return sensitive_data

    def anonymize(self, text: str) -> str:
        """
        Main anonymization method.
        Returns anonymized text with placeholders like [PER_1], [LOC_1], etc.
        """
        nlp = self.get_nlp()
        doc = nlp(text)
        anonymized_text = text
        target_entities = ["PER", "LOC", "ORG"]
        
        # Extract all names and sensitive data
        speaker_names = self.extract_speaker_names(text)
        mentioned_names = self.extract_mentioned_names(text)
        all_names = speaker_names.union(mentioned_names)
        sensitive_data = self.extract_sensitive_data(text)
        
        entities_to_replace = []
        
        # Add regex-detected names
        for name in all_names:
            for match in re.finditer(r'\b' + re.escape(name) + r'\b', text):
                entities_to_replace.append({
                    'text': name, 'start': match.start(), 'end': match.end(),
                    'label': 'PER', 'source': 'regex'
                })
        
        # Add spaCy NER entities
        for ent in doc.ents:
            if ent.label_ in target_entities:
                ent_text_clean = ent.text.lower().strip().rstrip('.')
                if ent_text_clean not in self.false_positives and len(ent.text) > 2:
                    label = 'PER' if ent.text in self.speaker_names else ent.label_
                    entities_to_replace.append({
                        'text': ent.text, 'start': ent.start_char, 'end': ent.end_char,
                        'label': label, 'source': 'spacy'
                    })
        
        # Add sensitive data patterns
        for data in sensitive_data:
            entities_to_replace.append({
                'text': data['text'], 'start': data['start'], 'end': data['end'],
                'label': data['label'], 'source': 'regex_sensitive'
            })
        
        # Deduplicate by position
        seen_positions = set()
        unique_entities = []
        for ent in entities_to_replace:
            key = (ent['start'], ent['end'])
            if key not in seen_positions:
                seen_positions.add(key)
                unique_entities.append(ent)
        
        # Sort by position (reverse) to replace from end to start
        entities_sorted = sorted(unique_entities, key=lambda x: x['start'], reverse=True)
        
        # Perform replacements
        for ent in entities_sorted:
            placeholder = self.get_or_create_placeholder(ent['text'], ent['label'])
            start, end = ent['start'], ent['end']
            anonymized_text = anonymized_text[:start] + placeholder + anonymized_text[end:]
        
        print(f"[ANON] Anonimizacion: {len(unique_entities)} entidades detectadas, {len(self.secret_map)} placeholders unicos")
        return anonymized_text

    def deanonymize(self, processed_text: str) -> str:
        """
        Restore original values from placeholders.
        Used after receiving AI response.
        """
        restored_text = processed_text
        for placeholder, original_value in self.secret_map.items():
            restored_text = restored_text.replace(placeholder, original_value)
        return restored_text
    
    def get_secret_map(self) -> dict:
        """Return the secret map for storage"""
        return self.secret_map.copy()
    
    def load_secret_map(self, secret_map: dict):
        """Load a previously saved secret map for deanonymization"""
        self.secret_map = secret_map.copy()


class GeminiProcessor:
    """
    Processes anonymized text with Google's Gemini API.
    Generates clinical notes from session transcripts.
    """
    
    def __init__(self, api_key: str = None):
        import google.generativeai as genai
        
        self.api_key = api_key or os.getenv('GEMINI_API_KEY')
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY no configurada. Anadela al archivo .env")
        
        genai.configure(api_key=self.api_key)
        self.model = genai.GenerativeModel('gemini-3-flash-preview')
        print("[OK] Gemini API configurada correctamente!")
    
    def generate_clinical_note(self, anonymized_text: str, patient_name: str = "Paciente") -> dict:
        """
        Generate clinical note from anonymized transcript.
        Returns dict with nota_clinica and metadata.
        """
        import time
        
        system_prompt = (
            "ACTÚA COMO: Sistema Automático de Documentación Clínica (SADC).\n"
            "CONTEXTO: Estás procesando transcripciones de sesiones terapéuticas para historias clínicas.\n"
            "SEGURIDAD: El texto input ya ha sido ANONIMIZADO. Los datos sensibles han sido reemplazados por placeholders (ej. [PER_1]).\n"
            "TAREA: Redactar una nota de evolución clínica formal, objetiva y profesional basada en la transcripción.\n"
            "INSTRUCCIONES DE CONTENIDO:\n"
            "1. NO censures síntomas ni relatos de pacientes. Es crucial para el expediente médico.\n"
            "2. Mantén un tono clínico, usando terminología psicológica adecuada.\n"
            "3. Resume la sintomatología, progreso y puntos clave tratados.\n"
            "FORMATO DE SALIDA (ESTRICTO): Un único objeto JSON válido. NO escribas nada fuera del JSON.\n"
            '{"nota_clinica": "Texto del párrafo de la nota en prosa continua..."}'
        )
        
        user_prompt = f"Conversación clínica:\n\n{anonymized_text}"
        full_prompt = f"{system_prompt}\n\n{user_prompt}"
        
        print("[GEMINI] Enviando texto anonimizado a Gemini...")
        
        # Configure safety settings to avoid blocking clinical content
        from google.generativeai.types import HarmCategory, HarmBlockThreshold
        safety_settings = {
            HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
        }
        
        try:
            start_time = time.time()
            response = self.model.generate_content(full_prompt, safety_settings=safety_settings)
            gen_duration = round(time.time() - start_time, 2)
            
            # Check if response was blocked or empty
            if not response.parts:
                print(f"[WARN] Gemini bloqueo la respuesta. Finish Reason: {response.prompt_feedback}")
                return {
                    'nota_clinica': "Error: El modelo de IA bloqueó la respuesta por políticas de seguridad.",
                    '_warning': 'Safety Block',
                    '_generation_time': gen_duration
                }
                
            response_text = response.text.strip()
            
            # Parse JSON response
            try:
                # Clean markdown code blocks
                if response_text.startswith('```'):
                    response_text = re.sub(r'^```json?\n?', '', response_text)
                    response_text = re.sub(r'\n?```$', '', response_text)
                
                result = json.loads(response_text)
                result['_generation_time'] = gen_duration
                return result
                
            except json.JSONDecodeError:
                # Fallback: treat entire response as the note
                return {
                    'nota_clinica': response_text,
                    '_warning': 'Formato no estructurado (JSON fallido)',
                    '_generation_time': gen_duration
                }
                
        except Exception as e:
            print(f"[ERROR] Error al llamar a Gemini: {e}")
            return {'error': f'Gemini Error: {str(e)}'}


def process_with_gemini(transcript_text: str, patient_name: str = "Paciente") -> tuple:
    """
    Complete anonymization + Gemini processing pipeline.
    
    Args:
        transcript_text: Raw transcription text
        patient_name: Patient name for context
        
    Returns:
        tuple: (final_json, secret_map)
        - final_json: The clinical note with metadata
        - secret_map: The placeholder->original mapping for storage
    """
    import time
    
    # 1. Initialize anonymizer
    anonymizer = SessionAnonymizer()
    
    # 2. Anonymize the transcript
    print("[ANON] Anonimizando transcripcion...")
    anonymized_text = anonymizer.anonymize(transcript_text)
    
    # 3. Process with Gemini
    try:
        processor = GeminiProcessor()
        result = processor.generate_clinical_note(anonymized_text, patient_name)
        
        if 'error' not in result:
            # 4. Deanonymize the response
            if 'nota_clinica' in result:
                raw_response = result['nota_clinica']
                print(f"\n--- [AUDITORIA] Respuesta Raw de Gemini (con placeholders) ---\n{raw_response}\n-------------------------------------------------------------")
                
                # Verify if placeholders exist in response
                placeholders_in_response = re.findall(r'\[[A-Z]+_\d+\]', raw_response)
                print(f"[AUDITORIA] Placeholders detectados en respuesta: {placeholders_in_response}")
                print(f"[AUDITORIA] Mapa secreto disponible: {list(anonymizer.get_secret_map().keys())}")
                
                result['nota_clinica'] = anonymizer.deanonymize(result['nota_clinica'])
                print(f"\n--- [AUDITORIA] Resultado Final (Des-anonimizado) ---\n{result['nota_clinica'][:100]}...\n-------------------------------------------------------------")
            
            # Add metadata
            result['_provider'] = 'gemini'
            result['_model_file'] = 'gemini-3-flash-preview'
            result['_anonymized'] = True
        
        return result, anonymizer.get_secret_map()
        
    except ValueError as e:
        return {'error': str(e)}, {}
    except Exception as e:
        return {'error': f'Processing error: {str(e)}'}, {}
