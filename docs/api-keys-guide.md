# Getting the free AI keys (no credit card)

You already have **Groq** and **Gemini**. Add these three. Each takes about 2 minutes. Use your normal email; none of
them asks for a card.

**Where keys go:**
1. Open `C:\Syntax_Assembler\Jarvis\.env` in Notepad.
2. Add one line per key, exactly as shown below. Don't put spaces around the `=`.
3. Save the file.

Never paste a key into a chat, a screenshot or GitHub. The `.env` file is never uploaded.

---

## 1. NVIDIA (build.nvidia.com): the big backup, about 40 requests a minute
1. Go to **https://build.nvidia.com** and click **Login** (top right). Sign up with your email and confirm it.
   If it asks, join the free **NVIDIA Developer Program**.
2. Open any model page, for example search **"gpt-oss-120b"** or **"llama-3.3-70b"**, and click it.
3. On the right, click **Get API Key**, then **Generate Key**.
4. Copy the key. It starts with `nvapi-`.
5. In `.env` add:
   ```
   NVIDIA_API_KEY=nvapi-xxxxxxxxxxxxxxxx
   ```

## 2. Mistral (console.mistral.ai): the coding backup (Codestral)
1. Go to **https://console.mistral.ai** and sign up with your email.
2. It asks you to pick a plan. Choose the **free plan** (named "Experiment" or "Free"). It may ask you to verify a
   phone number by SMS: that's normal and free.
3. In the left menu open **API Keys**, then **Create new key**. Give it a name like `jarvis` and leave the expiry
   empty or set it far away.
4. Copy the key straight away (it's shown only once).
5. In `.env` add:
   ```
   MISTRAL_API_KEY=xxxxxxxxxxxxxxxx
   ```
   Note: on the free plan Mistral may use what's sent to improve its models. Jarvis only sends text (what you said
   and the code or screen as text), never files or keys.

## 3. Cloudflare Workers AI: the last fallback (never trains on your data)
1. Go to **https://dash.cloudflare.com/sign-up**, sign up with your email and confirm it. Skip any "add a website"
   step.
2. In the left menu open **AI**, then **Workers AI**.
3. Click **Use REST API**.
4. Click **Create a Workers AI API Token**, leave the filled-in settings as they are, then click **Create API
   Token** and **Copy**.
5. On the same page, copy your **Account ID**.
6. In `.env` add both:
   ```
   CLOUDFLARE_API_TOKEN=xxxxxxxxxxxxxxxx
   CLOUDFLARE_ACCOUNT_ID=xxxxxxxxxxxxxxxx
   ```

---

## Check
After saving `.env`, tell Jarvis's builder (the chat) **"keys added"**. A test will call each provider once and show
a green tick or what's wrong. The key itself is never shown or printed.

## Already set up
- `GROQ_API_KEY`: Groq (console.groq.com → API Keys). The main brain and hearing.
- `GEMINI_API_KEY`: Google AI Studio (aistudio.google.com → Get API key). Screen understanding.
