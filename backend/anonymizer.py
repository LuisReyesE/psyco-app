import os
import re
import sys
import json
import time
import warnings
# Set console encoding to UTF-8 for Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        pass

# Suppress specific transformers warning that suggests a flag not supported by all versions
warnings.filterwarnings("ignore", message=".*fix_mistral_regex.*")

# from google import genai
# from google.genai import types
from dotenv import load_dotenv

load_dotenv()

# Define PROJECT_ROOT relative to this file (backend/anonymizer.py)
# This file is in .../psyco-app/backend/anonymizer.py
# Root is .../psyco-app/
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)

class SessionAnonymizer:
    """
    Hybrid PII anonymizer using:
    - GLiNER: Zero-shot NER for names, places, organizations (ML-based)
    - Presidio: Framework for structured PII (regex + context-aware)
    
    Replaces older spaCy-only implementation with high-recall hybrid approach.
    """
    
    _gliner_model = None  # Class-level cache
    _analyzer = None
    _anonymizer_engine = None
    
    def __init__(self):
        self.secret_map = {}
        self.reverse_map = {}
        self.counters = {
            'PER': 0, 'LOC': 0, 'ORG': 0,
            'DNI': 0, 'TEL': 0, 'EMAIL': 0, 'FECHA': 0, 'DIR': 0,
        }
        self.false_positives = {
            # Verbos comunes y gramática
            "haría", "pensé", "sentí", "suspira", "creí", "quería", "sabía",
            "tendría", "podría", "diría", "sería", "estaría", "vendría",
            "hice", "dije", "vine", "puse", "tuve", "supe", "quise",
            "porque", "entonces", "luego", "cuando", "donde", "quien", "como",
            # Roles y Relaciones
            "mamá", "papá", "padre", "madre", "hijo", "hija", "hermano", "hermana",
            "esposo", "esposa", "pareja", "novio", "novia",
            "abuelo", "abuela", "tío", "tía", "primo", "prima", "amigo", "amiga",
            "dr", "dr.", "psicólogo", "paciente", "terapeuta", "doctor",
            # Verbos Emocionales/Cognitivos
            "siento", "sentía", "siente", "sentimos",
            "pienso", "piensa", "pensaba",
            "creo", "creía", "creemos",
            "veo", "oigo", "escucho", "digo", "habla", "dice",
            "cuenta", "recuerda", "recuerdo", "olvido", "sufre",
            # Términos Clínicos
            "ansiedad", "depresión", "angustia", "terapia", "sesión",
            "cita", "consulta", "problema", "trastorno", "miedo",
            "pánico", "estrés", "duelo", "trauma", "crisis", "síntoma",
            "pastilla", "medicamento", "remedio", "dosis", "tratamiento",
            "metro", "calle", "avenida", "casa", "trabajo",
            # Títulos y prefijos (no son PII)
            "dra", "dra.", "ing", "ing.", "lic", "lic.", "sr", "sr.", "sra", "sra.",
            "don", "doña", "señor", "señora",
        }

    def warmup(self):
        """Force load models into memory (Background Warmup)"""
        print("[ANONYMIZER] Iniciando pre-carga de modelos (Warmup)...")
        try:
            self.get_presidio() # Carga SpaCy + Presidio
            self.get_gliner()   # Carga GLiNER
            print("[ANONYMIZER] Warmup completado: Modelos listos en RAM.")
        except Exception as e:
            print(f"[ANONYMIZER] Warmup warning: {e}")
    
    @classmethod
    def get_gliner(cls):
        """Lazy load GLiNER model from local path or HuggingFace"""
        if cls._gliner_model is None:
            # Lazy import to avoid heavy load at startup
            from gliner import GLiNER
            from transformers import AutoTokenizer
            from huggingface_hub import snapshot_download
            
            # Define local path
            local_path = os.path.join(PROJECT_ROOT, "backend", "models", "gliner_multi_v2.1")
            
            # Check if local model exists and has files
            if not os.path.exists(local_path) or not os.listdir(local_path):
                print(f"[GLiNER] No se encontró modelo en {local_path}.")
                print("[GLiNER] Descargando modelo 'urchade/gliner_multi-v2.1' a carpeta local...")
                try:
                    # Download files to the specific local directory
                    snapshot_download(repo_id="urchade/gliner_multi-v2.1", local_dir=local_path)
                    print("[GLiNER] Descarga completada exitosamente.")
                except Exception as e:
                    print(f"[ERROR] Falló la descarga del modelo: {e}")
                    # Fallback to remote cache if local download fails
                    print("[GLiNER] Intentando carga directa desde HuggingFace (cache)...")
                    cls._gliner_model = GLiNER.from_pretrained("urchade/gliner_multi-v2.1")
                    return cls._gliner_model

            print(f"[GLiNER] Cargando modelo DESDE DISCO LOCAL: {local_path}...")
            # FORCE OFFLINE MODE for this load
            os.environ["HF_HUB_OFFLINE"] = "1"
            
            try:
                # 1. Check if sentencepiece is actually importable (just for diagnostics)
                try:
                    import sentencepiece
                except ImportError:
                    print("[WARN] La librería 'sentencepiece' no parece estar disponible. GLiNER requiere esto para modo lento.")

                # 2. Standard local load (Default/Fast Mode)
                # Reverting to default behavior as GLiNER wrapper doesn't support manual tokenizer injection in this version.
                # The 'regex' warning is suppressed by filterwarnings above.
                try:
                    cls._gliner_model = GLiNER.from_pretrained(local_path, local_files_only=True)
                    print("[OK] Modelo GLiNER local cargado!")
                except Exception as e_local:
                     print(f"[ERROR] Falló carga local: {e_local}")
                     # If local fails, try remote but re-enable online mode temporarily
                     os.environ.pop("HF_HUB_OFFLINE", None) 
                     
                     print("[GLiNER] Intentando fallback remoto de emergencia...")
                     try:
                          cls._gliner_model = GLiNER.from_pretrained("urchade/gliner_multi-v2.1")
                          print("[OK] Modelo GLiNER remoto cargado!")
                     except Exception as e3:
                          print(f"[FATAL] No se pudo cargar GLiNER (Remoto fallo): {e3}")
                          return None

            except Exception as e_outer:
                 print(f"[FATAL] Error inesperado en estructura de carga GLiNER: {e_outer}")
                 return None

        return cls._gliner_model
    
    @classmethod 
    def get_presidio(cls):
        """Lazy load Presidio analyzer and anonymizer"""
        if cls._analyzer is None:
            from presidio_analyzer import AnalyzerEngine, PatternRecognizer, Pattern
            from presidio_analyzer.nlp_engine import NlpEngineProvider
            from presidio_anonymizer import AnonymizerEngine
            
            print("[Presidio] Configurando motor de análisis para español...")
            
            # Configure with spaCy Spanish model
            configuration = {
                "nlp_engine_name": "spacy",
                "models": [{"lang_code": "es", "model_name": "es_core_news_lg"}],
            }
            provider = NlpEngineProvider(nlp_configuration=configuration)
            nlp_engine = provider.create_engine()
            
            cls._analyzer = AnalyzerEngine(
                nlp_engine=nlp_engine,
                supported_languages=["es"]
            )
            
            # ── Custom Recognizers for Peruvian/Latin American PII ──
            
            # DNI Peruano (8 dígitos)
            dni_pattern = Pattern(name="dni_pattern", regex=r"\b\d{8}\b", score=0.5)
            dni_context_pattern = Pattern(
                name="dni_context_pattern",
                regex=r"(?:DNI|D\.N\.I\.|documento|identidad)[:\s]*(\d{8})\b",
                score=0.95
            )
            dni_recognizer = PatternRecognizer(
                supported_entity="DNI_PE",
                patterns=[dni_pattern, dni_context_pattern],
                context=["DNI", "documento", "identidad", "D.N.I"],
                supported_language="es",
                name="PeruvianDNIRecognizer"
            )
            
            # Teléfono Peruano (9 dígitos empezando con 9, o +51)
            tel_patterns = [
                Pattern(name="cel_pe", regex=r"\b9\d{8}\b", score=0.7),
                Pattern(name="cel_pe_intl", regex=r"\+51\s*9\d{8}", score=0.95),
                Pattern(name="tel_context", regex=r"(?:teléfono|celular|móvil|tel\.?|cel\.?)[:\s]*([\d\s\-\+\(\)]{7,15})", score=0.9),
            ]
            tel_recognizer = PatternRecognizer(
                supported_entity="PHONE_PE",
                patterns=tel_patterns,
                context=["teléfono", "celular", "móvil", "llamar", "número", "contacto"],
                supported_language="es",
                name="PeruvianPhoneRecognizer"
            )
            
            # Fechas en español
            date_patterns = [
                Pattern(name="date_slash", regex=r"\b\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}\b", score=0.8),
                Pattern(
                    name="date_text_es",
                    regex=r"\b\d{1,2}\s+de\s+(?:enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre)\s+(?:de\s+)?\d{2,4}\b",
                    score=0.9
                ),
            ]
            date_recognizer = PatternRecognizer(
                supported_entity="DATE_ES",
                patterns=date_patterns,
                supported_language="es",
                name="SpanishDateRecognizer"
            )
            
            # Direcciones peruanas
            dir_patterns = [
                Pattern(
                    name="dir_pe",
                    regex=r"(?:calle|av\.|avenida|jr\.|jirón|psje\.|pasaje)\s+[A-Za-záéíóúñÁÉÍÓÚÑ\s]+\d+[A-Za-z\s,\-]*",
                    score=0.85
                ),
            ]
            dir_recognizer = PatternRecognizer(
                supported_entity="ADDRESS_PE",
                patterns=dir_patterns,
                context=["vivo", "vivimos", "dirección", "domicilio", "ubicado"],
                supported_language="es",
                name="PeruvianAddressRecognizer"
            )
            
            # Add all custom recognizers
            cls._analyzer.registry.add_recognizer(dni_recognizer)
            cls._analyzer.registry.add_recognizer(tel_recognizer)
            cls._analyzer.registry.add_recognizer(date_recognizer)
            cls._analyzer.registry.add_recognizer(dir_recognizer)
            
            cls._anonymizer_engine = AnonymizerEngine()
            print("[OK] Presidio configurado con recognizers custom (DNI, TEL, FECHA, DIR)!")
        
        return cls._analyzer, cls._anonymizer_engine
    
    def get_or_create_placeholder(self, text: str, label: str) -> str:
        """Get existing placeholder or create a new one"""
        text_normalized = text.strip()
        key = (text_normalized, label)
        
        if key in self.reverse_map:
            return self.reverse_map[key]
        
        if label not in self.counters:
            self.counters[label] = 0
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
                # Filter out generic roles
                if speaker.lower() not in ['psicólogo', 'paciente', 'doctor', 'terapeuta']:
                    speakers.add(speaker)
        return speakers
    
    def anonymize(self, text: str, known_context: list = None) -> str:
        """
        Main anonymization using GLiNER (NER) + Presidio (structured PII).
        Returns anonymized text with placeholders like [PER_1], [LOC_1], etc.
        
        Args:
            text: The transcript to anonymize.
            known_context: Optional list of known names (e.g., patient name) to force-anonymize.
        """
        if not text:
            return ""

        anonymized_text = text
        entities_to_replace = []
        
        # ── PHASE 0: Known Context (Patient Name Priority) ──
        if known_context:
            print(f"[ANONYMIZER] Contexto conocido recibido: {known_context}")
            for name in known_context:
                if not name or len(name.strip()) < 3: 
                    continue
                
                # Normalize and split (e.g., "Mateo Mercado" -> ["Mateo Mercado", "Mateo", "Mercado"])
                name_clean = name.strip()
                tokens = name_clean.split()
                variants = [name_clean] + [t for t in tokens if len(t) > 3] # Only parts > 3 chars
                
                # Remove duplicates while preserving order
                variants = list(dict.fromkeys(variants))
                
                for variant in variants:
                    # Case-insensitive search using regex word boundaries
                    # Escape special regex chars in name just in case
                    import re
                    pattern = r'\b' + re.escape(variant) + r'\b'
                    for match in re.finditer(pattern, text, re.IGNORECASE):
                        entities_to_replace.append({
                            'text': text[match.start():match.end()], # Use exact text from doc
                            'start': match.start(),
                            'end': match.end(),
                            'label': 'PER',
                            'source': 'known_context',
                            'score': 1.0  # Max priority
                        })

        # ── PHASE 1: GLiNER Zero-Shot NER ──
        gliner = self.get_gliner()
        gliner_entities = []

        if gliner is None:
             print("[ANONYMIZER] GLiNER no disponible (probablemente offline/sin modelo). Saltando fase GLiNER.")
        else:
            gliner_labels = [
            "person", "location", "organization", 
            "hospital", "clinic", "company",
            "city", "district", "country"
        ]
        
            # Implement chunking to avoid truncation warnings (max_len=384 in config)
            # We use a window size of 300 words (approx) to be safe, or character based.
            # Simple character chunking with overlap is safer to avoid breaking words if careful, 
            # but GLiNER works on tokens. Let's use a conservative char limit.
            CHUNK_SIZE = 2048  # Approx 300-400 words? No, 384 tokens is ~1500 chars (depending on language)
                               # Warning said 708 tokens -> truncated. 
                               # Let's use a safe overlap strategy.
            
            # Simple overlapping window strategy
            window_size = 1000  # Characters (conservative, ~200-250 tokens)
            overlap = 200       # Overlap to catch entities at boundaries
            
            text_len = len(text)
            if text_len <= window_size:
                 gliner_entities = gliner.predict_entities(text, gliner_labels, threshold=0.4)
            else:
                cursor = 0
                while cursor < text_len:
                    end = min(cursor + window_size, text_len)
                    chunk_text = text[cursor:end]
                    
                    # Predict on chunk
                    chunk_entities = gliner.predict_entities(chunk_text, gliner_labels, threshold=0.4)
                    
                    # Adjust offsets
                    for ent in chunk_entities:
                        ent["start"] += cursor
                        ent["end"] += cursor
                        # Deduplicate/Filter later? We simply add all candidates.
                        # We might get duplicates in overlap regions.
                        gliner_entities.append(ent)
                    
                    if end == text_len:
                        break
                        
                    cursor += (window_size - overlap)
            
            # Deduplicate based on start/end to avoid double counting from overlap
            unique_gliner_entities = []
            seen_spans = set()
            for ent in gliner_entities:
                span = (ent["start"], ent["end"], ent["label"])
                if span not in seen_spans:
                    seen_spans.add(span)
                    unique_gliner_entities.append(ent)
            
            gliner_entities = unique_gliner_entities
        
        label_mapping = {
            "person": "PER",
            "location": "LOC", "city": "LOC", "district": "LOC", "country": "LOC",
            "organization": "ORG", "hospital": "ORG", "clinic": "ORG", "company": "ORG",
        }
        
        for ent in gliner_entities:
            ent_text = ent["text"].strip()
            ent_label = label_mapping.get(ent["label"], "ORG")
            ent_lower = ent_text.lower().strip().rstrip('.')
            
            if ent_lower in self.false_positives or len(ent_text) <= 2:
                continue
            
            # Find position in text
            for match in re.finditer(re.escape(ent_text), text):
                entities_to_replace.append({
                    'text': ent_text,
                    'start': match.start(),
                    'end': match.end(),
                    'label': ent_label,
                    'source': 'gliner',
                    'score': ent.get("score", 0)
                })
        
        # ── PHASE 2: Speaker names (regex) ──
        speaker_names = self.extract_speaker_names(text)
        for name in speaker_names:
            for match in re.finditer(r'\b' + re.escape(name) + r'\b', text):
                entities_to_replace.append({
                    'text': name, 'start': match.start(), 'end': match.end(),
                    'label': 'PER', 'source': 'speaker_regex', 'score': 1.0
                })
        
        # ── PHASE 3: Presidio Structured PII ──
        analyzer, _ = self.get_presidio()
        presidio_results = analyzer.analyze(
            text=text,
            language="es",
            entities=[
                "PERSON", "LOCATION", "ORGANIZATION",
                "EMAIL_ADDRESS", "PHONE_NUMBER",
                "DNI_PE", "PHONE_PE", "DATE_ES", "ADDRESS_PE"
            ],
            score_threshold=0.4
        )
        
        presidio_label_map = {
            "PERSON": "PER", "LOCATION": "LOC", "ORGANIZATION": "ORG",
            "EMAIL_ADDRESS": "EMAIL", "PHONE_NUMBER": "TEL",
            "DNI_PE": "DNI", "PHONE_PE": "TEL", "DATE_ES": "FECHA",
            "ADDRESS_PE": "DIR",
        }
        
        for result in presidio_results:
            ent_text = text[result.start:result.end].strip()
            ent_label = presidio_label_map.get(result.entity_type, "ORG")
            ent_lower = ent_text.lower().strip().rstrip('.')
            
            if ent_lower in self.false_positives or len(ent_text) <= 2:
                continue
                
            entities_to_replace.append({
                'text': ent_text,
                'start': result.start,
                'end': result.end,
                'label': ent_label,
                'source': 'presidio',
                'score': result.score
            })
        
        # ── PHASE 4: Deduplicate & Merge ──
        # When overlapping, prefer higher score, then GLiNER > Presidio
        # Known Context (score 1.0) will naturally win if sorted correctly
        entities_sorted = sorted(entities_to_replace, key=lambda x: (-x['score'], x['start']))
        
        occupied_ranges = []
        final_entities = []
        
        for ent in entities_sorted:
            s, e = ent['start'], ent['end']
            # Check overlap with already accepted entities
            overlaps = False
            for os_, oe_ in occupied_ranges:
                if s < oe_ and e > os_:  # overlap check
                    overlaps = True
                    break
            if not overlaps:
                final_entities.append(ent)
                occupied_ranges.append((s, e))
        
        # Sort by position (reverse) to replace from end to start
        final_entities.sort(key=lambda x: x['start'], reverse=True)
        
        # Perform replacements
        for ent in final_entities:
            placeholder = self.get_or_create_placeholder(ent['text'], ent['label'])
            start, end = ent['start'], ent['end']
            anonymized_text = anonymized_text[:start] + placeholder + anonymized_text[end:]
            
        if self.reverse_map:
            print(f"\n[ANONYMIZER] Entidades detectadas y protegidas ({len(self.reverse_map)}):")
            for (orig_text, label), placeholder in self.reverse_map.items():
                try:
                    # Solo mostramos el mapeo de seguridad
                    print(f"   * {placeholder} -> {label}") 
                except:
                    pass
            print(f"[ANONYMIZER] Total entidades protegidas: {len(self.reverse_map)}")
            print("--------------------------------------------------\n")
        else:
             print("\n[ANONYMIZER] No se detectaron entidades sensibles en este fragmento.\n")
        
        return anonymized_text
    
    def deanonymize(self, processed_text: str) -> str:
        """Restore original values from placeholders"""
        if not processed_text:
            return ""
            
        restored = processed_text
        for placeholder, original in self.secret_map.items():
            restored = restored.replace(placeholder, original)
        return restored
    
    def get_secret_map(self) -> dict:
        return self.secret_map.copy()



