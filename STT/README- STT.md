# consilience-dev

Real-time audio transcription with speaker diarization using multiple APIs.

## Setup

Install dependencies:
```bash
brew install portaudio
python -m pip install pyaudio assemblyai deepgram-sdk websockets python-dotenv
```

Create `.env` file:
```
ASSEMBLYAI_API_KEY=your_assemblyai_key
DEEPGRAM_API_KEY=your_deepgram_key
```

## Scripts

### deepgram.py
Real-time transcription with speaker diarization using Deepgram WebSocket API.
- Connects to wss://api.deepgram.com/v1/listen
- Parameters: diarize=true, model=nova-3, endpointing=100ms
- Returns Speaker_0, Speaker_1, etc. in real-time
- Saves to deepgram_conversation_{timestamp}.json

Run:
```bash
python deepgram.py
```

### assembly_ai.py
Real-time transcription using AssemblyAI streaming SDK.
- Uses AssemblyAI StreamingClient v3
- No speaker diarization in real-time (returns Speaker Unknown)
- Saves to conversation_{timestamp}.json

Run:
```bash
python assembly_ai.py
```

### whisper.py
Local transcription using OpenAI Whisper.
- Records audio chunks and transcribes locally
- No real-time streaming
- Saves to whisper_conversation_{timestamp}.json

Run:
```bash
python whisper.py
```

## API Keys

Get keys from:
- AssemblyAI: https://www.assemblyai.com/
- Deepgram: https://console.deepgram.com/

## Notes

Only Deepgram provides real-time speaker diarization. AssemblyAI requires batch processing for speaker labels.


**We have proceeded to move ahead with deepgram, not only because it has decent speech diarization, but at this time, its still faster at live transcription when compared to whisper**