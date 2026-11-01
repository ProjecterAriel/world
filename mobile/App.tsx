import React, { useEffect, useState } from "react";
import { ActivityIndicator, Alert, KeyboardAvoidingView, Platform, SafeAreaView, ScrollView, StatusBar, StyleSheet, Text, TextInput, TouchableOpacity, View } from "react-native";
import * as SecureStore from "expo-secure-store";
import { WebView } from "react-native-webview";

const API = "https://terra-ai.onrender.com";
type User = { id: string; nickname: string; email: string };
type Page = "earth" | "assistant" | "weather";
type Message = { role: "user" | "bot"; text: string };

export default function App() {
  const [token, setToken] = useState("");
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [mode, setMode] = useState<"login" | "register">("login");
  const [nickname, setNickname] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [page, setPage] = useState<Page>("earth");
  const [chatText, setChatText] = useState("");
  const [messages, setMessages] = useState<Message[]>([{ role: "bot", text: "Привет! Я Terra AI. Задайте вопрос о Земле, географии или погоде." }]);
  const [busy, setBusy] = useState(false);
  const [place, setPlace] = useState("");
  const [weather, setWeather] = useState("");

  async function request(path: string, body?: unknown, auth = true) {
    const headers: Record<string, string> = { "Content-Type": "application/json" };
    if (auth && token) headers.Authorization = "Bearer " + token;
    const response = await fetch(API + path, { method: body ? "POST" : "GET", headers, body: body ? JSON.stringify(body) : undefined });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || "Ошибка запроса");
    return data;
  }

  useEffect(() => {
    (async () => {
      try {
        const saved = await SecureStore.getItemAsync("terra_token");
        if (saved) {
          const response = await fetch(API + "/api/auth/me", { headers: { Authorization: "Bearer " + saved } });
          if (response.ok) {
            const data = await response.json();
            setToken(saved);
            setUser(data.user);
          } else await SecureStore.deleteItemAsync("terra_token");
        }
      } catch { /* A temporary network failure must not destroy a saved session. */ }
      finally { setLoading(false); }
    })();
  }, []);

  async function authenticate() {
    setError("");
    if (!email.trim() || !password) { setError("Введите email и пароль."); return; }
    if (mode === "register" && nickname.trim().length < 2) { setError("Никнейм должен содержать минимум 2 символа."); return; }
    setBusy(true);
    try {
      const response = await fetch(API + "/api/auth/" + mode, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ nickname: nickname.trim(), email: email.trim(), password })
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || "Не удалось выполнить вход");
      await SecureStore.setItemAsync("terra_token", data.token);
      setToken(data.token);
      setUser(data.user);
      setPassword("");
      setError("");
    } catch (e: any) { setError(e.message || "Ошибка соединения с сервером"); }
    finally { setBusy(false); }
  }

  async function logout() {
    await SecureStore.deleteItemAsync("terra_token");
    setToken(""); setUser(null); setPage("earth"); setPassword("");
  }

  async function sendChat() {
    const text = chatText.trim(); if (!text || busy) return;
    setChatText(""); setMessages(old => [...old, { role: "user", text }]); setBusy(true);
    try {
      const data = await request("/api/ai/chat", { message: text });
      setMessages(old => [...old, { role: "bot", text: data.reply }]);
    } catch (e: any) { setMessages(old => [...old, { role: "bot", text: e.message }]); }
    finally { setBusy(false); }
  }

  async function getWeather() {
    if (!place.trim()) return;
    setBusy(true); setWeather("Загружаю прогноз…");
    try {
      const response = await fetch(API + "/api/weather?place=" + encodeURIComponent(place), { headers: { Authorization: "Bearer " + token } });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Не удалось получить погоду");
      const first = data.list?.[0];
      const days = data.list?.filter((x: any) => x.dt_txt.includes("12:00:00")).slice(0, 5) || [];
      setWeather(data.city.name + "\n" + Math.round(first.main.temp) + "°C · " + first.weather[0].description + "\nОщущается как " + Math.round(first.main.feels_like) + "°C · влажность " + first.main.humidity + "%\n\n" + days.map((x: any) => new Date(x.dt * 1000).toLocaleDateString("ru-RU", { weekday: "short" }) + ": " + Math.round(x.main.temp) + "°C, " + x.weather[0].description).join("\n"));
    } catch (e: any) { setWeather(e.message); }
    finally { setBusy(false); }
  }

  if (loading) return <SafeAreaView style={styles.center}><ActivityIndicator size="large" color="#5bd8d0" /><Text style={styles.muted}>Загрузка Terra AI…</Text></SafeAreaView>;

  if (!user) return <SafeAreaView style={styles.authScreen}><StatusBar barStyle="light-content" /><KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : undefined} style={styles.authWrap}>
    <View style={styles.logo}><Text style={styles.logoMark}>◉</Text><Text style={styles.logoText}>TERRA <Text style={styles.accent}>AI</Text></Text></View>
    <Text style={styles.tagline}>Исследуй Землю. Спрашивай ИИ. Открывай новое.</Text>
    <View style={styles.switcher}><TouchableOpacity onPress={() => { setMode("login"); setError(""); }} style={[styles.switch, mode === "login" && styles.switchActive]}><Text style={styles.switchText}>Вход</Text></TouchableOpacity><TouchableOpacity onPress={() => { setMode("register"); setError(""); }} style={[styles.switch, mode === "register" && styles.switchActive]}><Text style={styles.switchText}>Регистрация</Text></TouchableOpacity></View>
    <ScrollView keyboardShouldPersistTaps="handled">
      {mode === "register" && <TextInput style={styles.input} placeholder="Никнейм" placeholderTextColor="#7890a5" value={nickname} onChangeText={setNickname} autoCapitalize="none" />}
      <TextInput style={styles.input} placeholder="Email" placeholderTextColor="#7890a5" value={email} onChangeText={setEmail} keyboardType="email-address" autoCapitalize="none" />
      <TextInput style={styles.input} placeholder="Пароль (минимум 8 символов)" placeholderTextColor="#7890a5" value={password} onChangeText={setPassword} secureTextEntry />
      {!!error && <Text style={styles.error}>{error}</Text>}
      <TouchableOpacity style={[styles.primary, busy && styles.disabled]} onPress={authenticate} disabled={busy}><Text style={styles.primaryText}>{busy ? "Подождите…" : mode === "register" ? "Создать аккаунт" : "Войти"}</Text></TouchableOpacity>
    </ScrollView>
  </KeyboardAvoidingView></SafeAreaView>;

  return <SafeAreaView style={styles.screen}><StatusBar barStyle="light-content" />
    <View style={styles.top}><View><Text style={styles.logoText}>TERRA <Text style={styles.accent}>AI</Text></Text><Text style={styles.muted}>Привет, {user.nickname}</Text></View><TouchableOpacity onPress={logout}><Text style={styles.logout}>Выйти ↗</Text></TouchableOpacity></View>
    <View style={styles.content}>
      {page === "earth" ? <WebView source={{ uri: API }} javaScriptEnabled domStorageEnabled style={{ flex: 1, backgroundColor: "#07111f" }} /> :
      page === "assistant" ? <View style={styles.panel}><Text style={styles.heading}>Общение с ИИ</Text><ScrollView style={styles.messages}>{messages.map((m, i) => <View key={i} style={[styles.bubble, m.role === "user" ? styles.userBubble : styles.botBubble]}><Text style={styles.body}>{m.text}</Text></View>)}{busy && <ActivityIndicator color="#5bd8d0" />}</ScrollView><View style={styles.composer}><TextInput style={[styles.input, styles.chatField]} placeholder="Напишите сообщение…" placeholderTextColor="#7890a5" value={chatText} onChangeText={setChatText} multiline /><TouchableOpacity style={styles.send} onPress={sendChat}><Text style={styles.primaryText}>➤</Text></TouchableOpacity></View></View> :
      <View style={styles.panel}><Text style={styles.heading}>Погода</Text><TextInput style={styles.input} placeholder="Город, например Tel Aviv" placeholderTextColor="#7890a5" value={place} onChangeText={setPlace} /><TouchableOpacity style={styles.primary} onPress={getWeather} disabled={busy}><Text style={styles.primaryText}>Узнать погоду</Text></TouchableOpacity><Text style={styles.weatherText}>{weather}</Text></View>}
    </View>
    <View style={styles.nav}>{(["earth", "assistant", "weather"] as Page[]).map((p, i) => <TouchableOpacity key={p} onPress={() => setPage(p)} style={[styles.navItem, page === p && styles.navSelected]}><Text style={[styles.navLabel, page === p && styles.accent]}>{["◎ Земля", "✧ ИИ", "☁ Погода"][i]}</Text></TouchableOpacity>)}</View>
  </SafeAreaView>;
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: "#07111f" }, authScreen: { flex: 1, backgroundColor: "#07111f", justifyContent: "center" }, authWrap: { padding: 25, width: "100%", maxWidth: 480, alignSelf: "center" }, center: { flex: 1, backgroundColor: "#07111f", alignItems: "center", justifyContent: "center", gap: 14 },
  logo: { flexDirection: "row", alignItems: "center", gap: 10 }, logoMark: { color: "#5bd8d0", fontSize: 38 }, logoText: { color: "#edf5fc", fontSize: 23, fontWeight: "800", letterSpacing: 2 }, accent: { color: "#5bd8d0" }, tagline: { color: "#8ba2b8", marginTop: 12, marginBottom: 25 },
  switcher: { flexDirection: "row", backgroundColor: "#0d1b2b", borderRadius: 12, padding: 4, marginBottom: 16 }, switch: { flex: 1, padding: 12, alignItems: "center", borderRadius: 9 }, switchActive: { backgroundColor: "#1b3449" }, switchText: { color: "#edf5fc", fontWeight: "600" },
  input: { backgroundColor: "#0d1b2b", borderColor: "#284158", borderWidth: 1, borderRadius: 10, padding: 14, color: "#fff", marginBottom: 12, fontSize: 15 }, primary: { backgroundColor: "#218f9a", padding: 15, borderRadius: 10, alignItems: "center", marginTop: 6 }, primaryText: { color: "#fff", fontWeight: "700", fontSize: 15 }, disabled: { opacity: 0.6 }, error: { color: "#ff8d8d", marginBottom: 10 }, muted: { color: "#8ba2b8", marginTop: 4 }, top: { paddingHorizontal: 16, paddingVertical: 12, flexDirection: "row", justifyContent: "space-between", alignItems: "center", borderBottomWidth: 1, borderBottomColor: "#20364b" }, logout: { color: "#ff9d9d" }, content: { flex: 1 }, panel: { flex: 1, padding: 16 }, heading: { color: "#edf5fc", fontSize: 22, fontWeight: "700", marginBottom: 16 }, messages: { flex: 1 }, bubble: { maxWidth: "88%", padding: 12, borderRadius: 12, marginVertical: 6 }, userBubble: { alignSelf: "flex-end", backgroundColor: "#14515a" }, botBubble: { alignSelf: "flex-start", backgroundColor: "#172e42" }, body: { color: "#edf5fc", lineHeight: 21 }, composer: { flexDirection: "row", alignItems: "center", gap: 8 }, chatField: { flex: 1, marginBottom: 0, maxHeight: 100 }, send: { backgroundColor: "#218f9a", borderRadius: 10, padding: 15 }, weatherText: { color: "#d6e4ef", marginTop: 20, lineHeight: 25 }, nav: { flexDirection: "row", backgroundColor: "#091725", borderTopWidth: 1, borderTopColor: "#20364b", paddingVertical: 10 }, navItem: { flex: 1, alignItems: "center", padding: 8, borderRadius: 8 }, navSelected: { backgroundColor: "#173249" }, navLabel: { color: "#9bb0c3", fontWeight: "600" }
});