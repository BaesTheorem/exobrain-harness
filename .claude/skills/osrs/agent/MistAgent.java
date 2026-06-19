import java.awt.*;
import java.awt.event.*;
import java.io.*;
import java.net.*;
import java.util.*;
import java.util.List;
import javax.swing.SwingUtilities;

/**
 * MIST in-process input agent for the Alora RuneLite client.
 * Loaded at launch via -javaagent. Opens a localhost socket and injects
 * AWT KeyEvents / MouseEvents straight into the game Canvas, bypassing
 * macOS key-window focus routing (so keyboard works while backgrounded).
 *
 * Eyes (screencapture -l) and background mouse (CGEventPostToPid) live on the
 * host side; this agent exists to solve the one thing those can't: keyboard.
 */
public class MistAgent {
    static volatile Canvas canvas;

    public static void premain(String args, java.lang.instrument.Instrumentation inst) {
        log("MistAgent premain loaded");
        Thread t = new Thread(MistAgent::serve, "mist-agent");
        t.setDaemon(true);
        t.start();
    }

    static void log(String s) { System.err.println("[mist-agent] " + s); }

    static void serve() {
        try (ServerSocket ss = new ServerSocket()) {
            ss.bind(new InetSocketAddress(InetAddress.getByName("127.0.0.1"), 43210));
            log("listening on 127.0.0.1:43210");
            while (true) {
                try (Socket s = ss.accept();
                     BufferedReader in = new BufferedReader(new InputStreamReader(s.getInputStream()));
                     PrintWriter out = new PrintWriter(s.getOutputStream(), true)) {
                    String line = in.readLine();
                    if (line != null) out.println(handle(line.trim()));
                } catch (Exception e) { log("conn err: " + e); }
            }
        } catch (Exception e) { log("server err: " + e); }
    }

    static String handle(String cmd) {
        try {
            if (cmd.equals("ping")) return "pong";
            if (cmd.equals("find")) { Canvas c = findCanvas(); return c == null ? "NO_CANVAS" : "CANVAS " + c.getWidth() + "x" + c.getHeight() + " focusable=" + c.isFocusable() + " showing=" + c.isShowing(); }
            if (cmd.equals("info")) return inventory();
            if (cmd.equals("tree")) return tree();
            if (cmd.startsWith("clickcomp ")) return clickComp(cmd.substring(10).trim());
            if (cmd.equals("gamestate")) return gamestate();
            if (cmd.equals("state")) return state();
            if (cmd.equals("npcs")) return npcs();
            if (cmd.startsWith("clicknpc ")) return clickNpc(cmd.substring(9).trim());
            if (cmd.startsWith("type ")) { typeText(cmd.substring(5)); return "OK typed " + (cmd.length() - 5) + " chars"; }
            if (cmd.equals("clear")) { for (int i = 0; i < 32; i++) specialKey("BACKSPACE"); return "OK clear"; }
            if (cmd.startsWith("key ")) { specialKey(cmd.substring(4).trim()); return "OK key " + cmd.substring(4).trim(); }
            if (cmd.startsWith("click ")) { String[] p = cmd.substring(6).trim().split("\\s+"); clickCanvas(Integer.parseInt(p[0]), Integer.parseInt(p[1])); return "OK click " + p[0] + "," + p[1]; }
            return "UNKNOWN " + cmd;
        } catch (Exception e) { return "ERR " + e; }
    }

    static String inventory() {
        StringBuilder sb = new StringBuilder();
        for (Frame f : Frame.getFrames()) {
            sb.append("FRAME '").append(f.getTitle()).append("' ").append(f.getWidth()).append("x").append(f.getHeight()).append(" showing=").append(f.isShowing()).append("; ");
            collect(f, sb, 0);
        }
        return sb.length() == 0 ? "NO_FRAMES" : sb.toString();
    }
    static void collect(Container c, StringBuilder sb, int d) {
        for (Component k : c.getComponents()) {
            if (k instanceof Canvas) sb.append("[Canvas ").append(k.getWidth()).append("x").append(k.getHeight()).append(" showing=").append(k.isShowing()).append("] ");
            if (k instanceof Container && d < 6) collect((Container) k, sb, d + 1);
        }
    }

    static String tree() {
        StringBuilder sb = new StringBuilder();
        for (Frame f : Frame.getFrames()) { if (!f.isShowing()) continue; sb.append("=FRAME '").append(f.getTitle()).append("'\n"); dump(f, sb, 1); }
        return sb.length() == 0 ? "NO_SHOWING_FRAMES" : sb.toString();
    }
    static void dump(Container c, StringBuilder sb, int d) {
        for (Component k : c.getComponents()) {
            String txt = "";
            if (k instanceof javax.swing.AbstractButton) txt = "btn'" + ((javax.swing.AbstractButton) k).getText() + "'";
            else if (k instanceof javax.swing.JLabel) txt = "lbl'" + ((javax.swing.JLabel) k).getText() + "'";
            Rectangle r = k.getBounds();
            for (int i = 0; i < d; i++) sb.append(' ');
            sb.append(k.getClass().getSimpleName()).append(' ').append(r.width).append('x').append(r.height).append(" show=").append(k.isShowing()).append(' ').append(txt).append('\n');
            if (k instanceof Container && d < 8) dump((Container) k, sb, d + 1);
        }
    }

    static String clickComp(String sub) throws Exception {
        final String needle = sub.toLowerCase();
        Component match = null;
        for (Frame f : Frame.getFrames()) { if (!f.isShowing()) continue; match = search(f, needle); if (match != null) break; }
        if (match == null) return "NO_MATCH";
        final Component c = match;
        onEdt(() -> {
            if (c instanceof javax.swing.AbstractButton) { ((javax.swing.AbstractButton) c).doClick(); }
            else {
                int x = c.getWidth() / 2, y = c.getHeight() / 2; long t = System.currentTimeMillis();
                c.dispatchEvent(new MouseEvent(c, MouseEvent.MOUSE_PRESSED, t, InputEvent.BUTTON1_DOWN_MASK, x, y, 1, false, MouseEvent.BUTTON1));
                c.dispatchEvent(new MouseEvent(c, MouseEvent.MOUSE_RELEASED, t, InputEvent.BUTTON1_DOWN_MASK, x, y, 1, false, MouseEvent.BUTTON1));
                c.dispatchEvent(new MouseEvent(c, MouseEvent.MOUSE_CLICKED, t, InputEvent.BUTTON1_DOWN_MASK, x, y, 1, false, MouseEvent.BUTTON1));
            }
        });
        return "OK clickcomp " + c.getClass().getSimpleName();
    }
    static Component search(Container c, String needle) {
        for (Component k : c.getComponents()) {
            String txt = null;
            if (k instanceof javax.swing.AbstractButton) txt = ((javax.swing.AbstractButton) k).getText();
            else if (k instanceof javax.swing.JLabel) txt = ((javax.swing.JLabel) k).getText();
            if (txt != null && txt.toLowerCase().contains(needle)) return k;
            if (k instanceof Container) { Component r = search((Container) k, needle); if (r != null) return r; }
        }
        return null;
    }

    // ---- RuneLite game-state reflection ----
    static Object CLIENT;
    static Object client() throws Exception {
        if (CLIENT != null) return CLIENT;
        Class<?> rl = Class.forName("net.runelite.client.RuneLite");
        Object inj = rl.getMethod("getInjector").invoke(null);
        // get getInstance from the PUBLIC Injector interface (impl class is non-public -> IllegalAccess)
        java.lang.reflect.Method gi = Class.forName("com.google.inject.Injector").getMethod("getInstance", Class.class);
        gi.setAccessible(true);
        CLIENT = gi.invoke(inj, Class.forName("net.runelite.api.Client"));
        return CLIENT;
    }
    // invoke a no/var-arg method (matched by name + arg count) declared on the given interface/class
    static Object call(Object target, String cls, String method, Object... args) throws Exception {
        Class<?> c = Class.forName(cls);
        for (java.lang.reflect.Method m : c.getMethods())
            if (m.getName().equals(method) && m.getParameterCount() == args.length) return m.invoke(target, args);
        throw new NoSuchMethodException(cls + "." + method + "/" + args.length);
    }
    static int planeOf(Object cl) throws Exception { return (int) call(cl, "net.runelite.api.Client", "getPlane"); }

    static String gamestate() {
        try {
            Object cl = client();
            Object gs = call(cl, "net.runelite.api.Client", "getGameState");
            return gs == null ? "null" : gs.toString();   // STARTING/LOGIN_SCREEN/LOGGING_IN/LOADING/LOGGED_IN/...
        } catch (Throwable t) { return "GS_ERR " + t; }
    }

    static String state() {
        try {
            Object cl = client();
            Object lp = call(cl, "net.runelite.api.Client", "getLocalPlayer");
            if (lp == null) return "NO_PLAYER (not logged in / loading)";
            Object wp = call(lp, "net.runelite.api.Actor", "getWorldLocation");
            int x = (int) call(wp, "net.runelite.api.coords.WorldPoint", "getX");
            int y = (int) call(wp, "net.runelite.api.coords.WorldPoint", "getY");
            int p = (int) call(wp, "net.runelite.api.coords.WorldPoint", "getPlane");
            Object nm = call(lp, "net.runelite.api.Actor", "getName");
            Object hp = "?"; try { hp = call(lp, "net.runelite.api.Actor", "getHealthRatio"); } catch (Exception ignore) {}
            return "PLAYER name=" + nm + " world=" + x + "," + y + "," + p;
        } catch (Throwable t) { return "STATE_ERR " + t; }
    }

    static java.lang.reflect.Method L2C;
    static int[] canvasPt(Object cl, Object localPoint, int plane) throws Exception {
        if (L2C == null) {
            Class<?> persp = Class.forName("net.runelite.api.Perspective");
            for (java.lang.reflect.Method m : persp.getMethods())
                if (m.getName().equals("localToCanvas") && m.getParameterCount() == 3 && m.getParameterTypes()[2] == int.class) { L2C = m; break; }
        }
        Object pt = L2C.invoke(null, cl, localPoint, plane);
        if (pt == null) return null;
        // RuneLite returns net.runelite.api.Point (getX/getY methods); java.awt.Point has x/y fields
        int x, y;
        try { x = (int) pt.getClass().getMethod("getX").invoke(pt); y = (int) pt.getClass().getMethod("getY").invoke(pt); }
        catch (NoSuchMethodException e) { x = pt.getClass().getField("x").getInt(pt); y = pt.getClass().getField("y").getInt(pt); }
        if (x < 0 || y < 0) return null;   // off-screen sentinel
        return new int[]{x, y};
    }

    static String npcs() {
        try {
            Object cl = client();
            int plane = planeOf(cl);
            Object list = call(cl, "net.runelite.api.Client", "getNpcs");
            java.util.List<?> ns = (java.util.List<?>) list;
            StringBuilder sb = new StringBuilder();
            int n = 0;
            for (Object npc : ns) {
                if (npc == null) continue;
                Object nm = call(npc, "net.runelite.api.Actor", "getName");
                Object loc = call(npc, "net.runelite.api.Actor", "getLocalLocation");
                if (loc == null) continue;
                int[] pt = canvasPt(cl, loc, plane);
                if (pt == null) continue;             // off-screen
                sb.append(nm).append("@").append(pt[0]).append(",").append(pt[1]).append("; ");
                if (++n > 60) break;
            }
            return sb.length() == 0 ? "NO_NPCS_ON_SCREEN" : sb.toString();
        } catch (Throwable t) { return "NPCS_ERR " + t; }
    }

    static String clickNpc(String namePart) {
        try {
            Object cl = client();
            int plane = planeOf(cl);
            java.util.List<?> ns = (java.util.List<?>) call(cl, "net.runelite.api.Client", "getNpcs");
            String needle = namePart.toLowerCase();
            Object best = null; int[] bestPt = null;
            for (Object npc : ns) {
                if (npc == null) continue;
                Object nm = call(npc, "net.runelite.api.Actor", "getName");
                if (nm == null || !nm.toString().toLowerCase().contains(needle)) continue;
                Object loc = call(npc, "net.runelite.api.Actor", "getLocalLocation");
                if (loc == null) continue;
                int[] pt = canvasPt(cl, loc, plane);
                if (pt == null) continue;
                best = nm; bestPt = pt; break;
            }
            if (bestPt == null) return "NPC_NOT_FOUND_ONSCREEN " + namePart;
            clickCanvas(bestPt[0], bestPt[1]);
            return "OK clicknpc '" + best + "' @" + bestPt[0] + "," + bestPt[1];
        } catch (Throwable t) { return "CLICKNPC_ERR " + t; }
    }

    static Canvas findCanvas() {
        Canvas best = null; long bestArea = 0;
        for (Frame f : Frame.getFrames()) {
            for (Canvas c : canvasesIn(f)) {
                long a = (long) c.getWidth() * c.getHeight();
                if (c.isShowing() && a > bestArea) { best = c; bestArea = a; }
            }
        }
        canvas = best; return best;
    }
    static List<Canvas> canvasesIn(Container c) {
        List<Canvas> r = new ArrayList<>();
        for (Component k : c.getComponents()) {
            if (k instanceof Canvas) r.add((Canvas) k);
            if (k instanceof Container) r.addAll(canvasesIn((Container) k));
        }
        return r;
    }

    static void onEdt(Runnable r) throws Exception { SwingUtilities.invokeAndWait(r); }

    static void typeText(String text) throws Exception {
        final Canvas c = findCanvas();
        if (c == null) throw new IllegalStateException("no canvas");
        onEdt(() -> {
            for (char ch : text.toCharArray()) {
                long t = System.currentTimeMillis();
                int kc = KeyEvent.getExtendedKeyCodeForChar(ch);
                c.dispatchEvent(new KeyEvent(c, KeyEvent.KEY_PRESSED, t, 0, kc, ch));
                c.dispatchEvent(new KeyEvent(c, KeyEvent.KEY_TYPED, t, 0, KeyEvent.VK_UNDEFINED, ch));
                c.dispatchEvent(new KeyEvent(c, KeyEvent.KEY_RELEASED, t, 0, kc, ch));
            }
        });
    }

    static void specialKey(String name) throws Exception {
        final Canvas c = findCanvas();
        if (c == null) throw new IllegalStateException("no canvas");
        int kc; char ch = KeyEvent.CHAR_UNDEFINED;
        switch (name.toUpperCase()) {
            case "ENTER": kc = KeyEvent.VK_ENTER; ch = '\n'; break;
            case "SPACE": kc = KeyEvent.VK_SPACE; ch = ' '; break;
            case "BACKSPACE": kc = KeyEvent.VK_BACK_SPACE; ch = '\b'; break;
            case "TAB": kc = KeyEvent.VK_TAB; ch = '\t'; break;
            case "ESC": kc = KeyEvent.VK_ESCAPE; break;
            default: throw new IllegalArgumentException("unknown key " + name);
        }
        final int fkc = kc; final char fch = ch;
        onEdt(() -> {
            long t = System.currentTimeMillis();
            c.dispatchEvent(new KeyEvent(c, KeyEvent.KEY_PRESSED, t, 0, fkc, fch));
            if (fch != KeyEvent.CHAR_UNDEFINED) c.dispatchEvent(new KeyEvent(c, KeyEvent.KEY_TYPED, t, 0, KeyEvent.VK_UNDEFINED, fch));
            c.dispatchEvent(new KeyEvent(c, KeyEvent.KEY_RELEASED, t, 0, fkc, fch));
        });
    }

    static void clickCanvas(int x, int y) throws Exception {
        final Canvas c = findCanvas();
        if (c == null) throw new IllegalStateException("no canvas");
        onEdt(() -> {
            long t = System.currentTimeMillis();
            c.dispatchEvent(new MouseEvent(c, MouseEvent.MOUSE_MOVED, t, 0, x, y, 0, false));
            c.dispatchEvent(new MouseEvent(c, MouseEvent.MOUSE_PRESSED, t, InputEvent.BUTTON1_DOWN_MASK, x, y, 1, false, MouseEvent.BUTTON1));
            c.dispatchEvent(new MouseEvent(c, MouseEvent.MOUSE_RELEASED, t, InputEvent.BUTTON1_DOWN_MASK, x, y, 1, false, MouseEvent.BUTTON1));
            c.dispatchEvent(new MouseEvent(c, MouseEvent.MOUSE_CLICKED, t, InputEvent.BUTTON1_DOWN_MASK, x, y, 1, false, MouseEvent.BUTTON1));
        });
    }
}
