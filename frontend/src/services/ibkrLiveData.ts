/**
 * IBKR Live Data Service — WebSocket subscription for real-time chain updates.
 * Gracefully degrades to polling if WS unavailable.
 */

export interface LiveQuote {
  ticker: string;
  lastPrice: number;
  bid: number;
  ask: number;
  bidSize: number;
  askSize: number;
  timestamp: number;
}

export interface ChainUpdate {
  ticker: string;
  shortStrike: number;
  longStrike: number;
  optionType: string;
  credit: number;
  iv: number;
  delta: number;
  gamma: number;
  theta: number;
  vega: number;
  timestamp: number;
}

type Callback = (data: LiveQuote | ChainUpdate) => void;

class IBKRLiveDataService {
  private ws: WebSocket | null = null;
  private subscribers: Map<string, Set<Callback>> = new Map();
  private connected = false;
  private reconnectAttempts = 0;
  private maxReconnectAttempts = 5;
  private reconnectDelay = 2000;
  private heartbeatInterval: NodeJS.Timeout | null = null;

  /**
   * Connect to IBKR WebSocket for live data.
   * Falls back gracefully if unavailable.
   */
  connect(): Promise<boolean> {
    return new Promise((resolve) => {
      // Detect if we're in a browser with WebSocket support
      if (typeof window === "undefined" || !("WebSocket" in window)) {
        console.warn("WebSocket not available in this environment");
        resolve(false);
        return;
      }

      try {
        // Connect to backend proxy that forwards to IBKR
        const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
        const wsUrl = `${protocol}//${window.location.host}/api/ibkr/live`;

        this.ws = new WebSocket(wsUrl);

        this.ws.onopen = () => {
          console.log("IBKR Live Data connected");
          this.connected = true;
          this.reconnectAttempts = 0;
          this.startHeartbeat();
          resolve(true);
        };

        this.ws.onmessage = (event) => {
          try {
            const data = JSON.parse(event.data);
            this.handleMessage(data);
          } catch (e) {
            console.error("Failed to parse WebSocket message:", e);
          }
        };

        this.ws.onerror = (event) => {
          console.error("IBKR WebSocket error:", event);
          this.connected = false;
          resolve(false);
        };

        this.ws.onclose = () => {
          console.warn("IBKR WebSocket closed, attempting reconnect...");
          this.connected = false;
          this.attemptReconnect();
        };

        // Timeout if connection doesn't establish
        setTimeout(() => {
          if (!this.connected) {
            this.ws?.close();
            resolve(false);
          }
        }, 5000);
      } catch (e) {
        console.error("Failed to create WebSocket:", e);
        resolve(false);
      }
    });
  }

  /**
   * Subscribe to live updates for a ticker/strike.
   */
  subscribe(key: string, callback: Callback): () => void {
    if (!this.subscribers.has(key)) {
      this.subscribers.set(key, new Set());
    }
    this.subscribers.get(key)!.add(callback);

    // Send subscription message
    if (this.connected && this.ws) {
      this.ws.send(JSON.stringify({ action: "subscribe", key }));
    }

    // Return unsubscribe function
    return () => {
      const callbacks = this.subscribers.get(key);
      if (callbacks) {
        callbacks.delete(callback);
        if (callbacks.size === 0) {
          this.subscribers.delete(key);
          if (this.connected && this.ws) {
            this.ws.send(JSON.stringify({ action: "unsubscribe", key }));
          }
        }
      }
    };
  }

  /**
   * Handle incoming message from WebSocket.
   */
  private handleMessage(data: any) {
    const key = data.key || `${data.ticker}:${data.shortStrike}:${data.longStrike}`;
    const callbacks = this.subscribers.get(key);
    if (callbacks) {
      callbacks.forEach((cb) => cb(data));
    }
  }

  /**
   * Attempt to reconnect with exponential backoff.
   */
  private attemptReconnect() {
    if (this.reconnectAttempts >= this.maxReconnectAttempts) {
      console.error("Max reconnection attempts reached, giving up");
      return;
    }

    this.reconnectAttempts++;
    const delay = this.reconnectDelay * Math.pow(2, this.reconnectAttempts - 1);
    console.log(`Reconnecting in ${delay}ms (attempt ${this.reconnectAttempts})`);

    setTimeout(() => {
      this.connect();
    }, delay);
  }

  /**
   * Send heartbeat to keep connection alive.
   */
  private startHeartbeat() {
    this.heartbeatInterval = setInterval(() => {
      if (this.connected && this.ws) {
        this.ws.send(JSON.stringify({ action: "ping" }));
      }
    }, 30000); // 30 seconds
  }

  /**
   * Disconnect from IBKR WebSocket.
   */
  disconnect() {
    if (this.heartbeatInterval) {
      clearInterval(this.heartbeatInterval);
    }
    if (this.ws) {
      this.ws.close();
    }
    this.connected = false;
    this.subscribers.clear();
  }

  /**
   * Check if connected.
   */
  isConnected(): boolean {
    return this.connected;
  }
}

export const ibkrLiveData = new IBKRLiveDataService();
