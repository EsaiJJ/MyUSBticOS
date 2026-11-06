package com.portablevault.vault;

import android.app.Activity;
import android.content.ContentResolver;
import android.content.Intent;
import android.content.SharedPreferences;
import android.database.Cursor;
import android.graphics.Color;
import android.net.Uri;
import android.os.Bundle;
import android.provider.DocumentsContract;
import android.text.method.ScrollingMovementMethod;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;

import java.io.BufferedReader;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.util.ArrayList;
import java.util.List;

/**
 * Portable Privacy Vault - Android companion app.
 *
 * Uses the Storage Access Framework (SAF) to read and write the vault that
 * lives on the USB-OTG drive: Vault/SharedData/...  The exact same files are
 * visible to the Windows and Linux launchers.
 *
 * Fully self-contained (no third-party libraries) so it can be built with the
 * plain Android build-tools.
 */
public class MainActivity extends Activity {

    private static final int REQ_PICK_DIR = 1001;
    private static final String PREFS = "vault";
    private static final String KEY_TREE = "tree_uri";

    private TextView status;
    private TextView contents;
    private Uri treeUri;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(36, 36, 36, 36);

        TextView title = new TextView(this);
        title.setText("Portable Privacy Vault");
        title.setTextSize(22);
        title.setGravity(Gravity.CENTER_HORIZONTAL);

        TextView sub = new TextView(this);
        sub.setText("Browse the USB vault; SharedData is your workspace.");
        sub.setPadding(0, 8, 0, 24);

        Button pick = new Button(this);
        pick.setText("Select vault USB folder");
        pick.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View v) { pickFolder(); }
        });

        Button showContents = new Button(this);
        showContents.setText("List SharedData contents");
        showContents.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View v) { listSharedData(); }
        });

        Button showConfig = new Button(this);
        showConfig.setText("Show vault config.json");
        showConfig.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View v) { showConfig(); }
        });

        Button termux = new Button(this);
        termux.setText("Open workspace in Termux");
        termux.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View v) { openInTermux(); }
        });

        status = new TextView(this);
        status.setPadding(0, 16, 0, 16);

        contents = new TextView(this);
        contents.setTextSize(13);
        contents.setTextIsSelectable(true);
        contents.setMovementMethod(new ScrollingMovementMethod());
        contents.setBackgroundColor(Color.parseColor("#F0F0F0"));
        contents.setPadding(24, 24, 24, 24);
        contents.setText("No folder selected yet.");

        ScrollView scroll = new ScrollView(this);
        scroll.addView(contents, new ViewGroup.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));

        root.addView(title);
        root.addView(sub);
        root.addView(pick);
        root.addView(showContents);
        root.addView(showConfig);
        root.addView(termux);
        root.addView(status);
        root.addView(scroll, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f));

        setContentView(root);

        SharedPreferences prefs = getSharedPreferences(PREFS, MODE_PRIVATE);
        String saved = prefs.getString(KEY_TREE, null);
        if (saved != null) {
            treeUri = Uri.parse(saved);
            status.setText("Using saved vault folder.");
            listSharedData();
        } else {
            status.setText("Select the USB drive, then the Vault folder.");
        }
    }

    private void pickFolder() {
        Intent intent = new Intent(Intent.ACTION_OPEN_DOCUMENT_TREE);
        intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION
                | Intent.FLAG_GRANT_WRITE_URI_PERMISSION
                | Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION);
        try {
            startActivityForResult(intent, REQ_PICK_DIR);
        } catch (Exception e) {
            toast("No file picker available: " + e.getMessage());
        }
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode != REQ_PICK_DIR || resultCode != RESULT_OK || data == null) {
            return;
        }
        Uri uri = data.getData();
        if (uri == null) {
            return;
        }
        final int flags = data.getFlags()
                & (Intent.FLAG_GRANT_READ_URI_PERMISSION
                | Intent.FLAG_GRANT_WRITE_URI_PERMISSION);
        try {
            getContentResolver().takePersistableUriPermission(uri, flags);
        } catch (SecurityException ignored) {
            // Some providers do not grant persistable permission.
        }
        treeUri = uri;
        getSharedPreferences(PREFS, MODE_PRIVATE).edit()
                .putString(KEY_TREE, uri.toString()).apply();
        status.setText("Vault folder selected:\n" + uri);
        listSharedData();
    }

    // ---- SAF helpers -----------------------------------------------------

    private List<String[]> listChildren(String parentDocId) {
        List<String[]> out = new ArrayList<>();
        ContentResolver cr = getContentResolver();
        Uri children = DocumentsContract.buildChildDocumentsUriUsingTree(treeUri, parentDocId);
        Cursor c = null;
        try {
            c = cr.query(children, new String[]{
                    DocumentsContract.Document.COLUMN_DOCUMENT_ID,
                    DocumentsContract.Document.COLUMN_DISPLAY_NAME,
                    DocumentsContract.Document.COLUMN_MIME_TYPE,
                    DocumentsContract.Document.COLUMN_SIZE
            }, null, null, null);
            if (c != null) {
                while (c.moveToNext()) {
                    out.add(new String[]{c.getString(0), c.getString(1), c.getString(2),
                            c.isNull(3) ? "" : c.getString(3)});
                }
            }
        } catch (Exception e) {
            toast("List failed: " + e.getMessage());
        } finally {
            if (c != null) c.close();
        }
        return out;
    }

    private String findChildDocId(String parentDocId, String name) {
        for (String[] row : listChildren(parentDocId)) {
            if (name.equalsIgnoreCase(row[1])
                    && DocumentsContract.Document.MIME_TYPE_DIR.equals(row[2])) {
                return row[0];
            }
        }
        return null;
    }

    /** Resolve .../Vault/SharedData doc id from the picked tree root. */
    private String resolveSharedData() {
        if (treeUri == null) {
            status.setText("Select the vault USB folder first.");
            return null;
        }
        String rootId;
        try {
            rootId = DocumentsContract.getTreeDocumentId(treeUri);
        } catch (Exception e) {
            return null;
        }
        // The user may have picked the drive root or the Vault folder directly.
        String vaultId = findChildDocId(rootId, "Vault");
        if (vaultId == null) {
            // maybe they picked Vault itself
            if (findChildDocId(rootId, "SharedData") != null) {
                vaultId = rootId;
            }
        }
        if (vaultId == null) {
            return null;
        }
        return findChildDocId(vaultId, "SharedData");
    }

    private void listSharedData() {
        String sharedId = resolveSharedData();
        if (sharedId == null) {
            contents.setText("Could not find Vault/SharedData inside the selected folder.\n\n"
                    + "Pick the drive root that contains the 'Vault' folder.");
            return;
        }
        List<String[]> rows = listChildren(sharedId);
        StringBuilder sb = new StringBuilder();
        sb.append("Vault/SharedData (").append(rows.size()).append(" entries)\n\n");
        for (String[] row : rows) {
            boolean dir = DocumentsContract.Document.MIME_TYPE_DIR.equals(row[2]);
            sb.append(dir ? "[DIR]  " : "[FILE] ");
            sb.append(row[1]);
            if (!dir && row[3] != null && row[3].length() > 0) {
                try {
                    long size = Long.parseLong(row[3]);
                    sb.append("  (").append(size).append(" bytes)");
                } catch (NumberFormatException ignored) { }
            }
            sb.append("\n");
        }
        contents.setText(sb.toString());
        status.setText("Loaded SharedData from the USB vault.");
    }

    private void showConfig() {
        String sharedId = resolveSharedData();
        if (sharedId == null) {
            status.setText("Select the vault USB folder first.");
            return;
        }
        String vaultId = findChildDocId(DocumentsContract.getTreeDocumentId(treeUri), "Vault");
        if (vaultId == null) vaultId = DocumentsContract.getTreeDocumentId(treeUri);
        String configId = findChildDocId(vaultId, "config.json");
        if (configId == null) {
            contents.setText("config.json not found in Vault/.");
            return;
        }
        Uri doc = DocumentsContract.buildDocumentUriUsingTree(treeUri, configId);
        StringBuilder sb = new StringBuilder();
        InputStream in = null;
        BufferedReader reader = null;
        try {
            in = getContentResolver().openInputStream(doc);
            if (in != null) {
                reader = new BufferedReader(new InputStreamReader(in, "UTF-8"));
                String line;
                while ((line = reader.readLine()) != null) {
                    sb.append(line).append('\n');
                }
            }
        } catch (Exception e) {
            sb.append("Read error: ").append(e.getMessage());
        } finally {
            try { if (reader != null) reader.close(); } catch (Exception ignored) { }
            try { if (in != null) in.close(); } catch (Exception ignored) { }
        }
        contents.setText(sb.length() == 0 ? "(empty config)" : sb.toString());
        status.setText("Showing Vault/config.json");
    }

    private void openInTermux() {
        Intent i = new Intent("com.termux.RUN_COMMAND");
        i.setClassName("com.termux", "com.termux.app.RunCommandService");
        i.putExtra("com.termux.RUN_COMMAND_PATH",
                "/data/data/com.termux/files/usr/bin/bash");
        i.putExtra("com.termux.RUN_COMMAND_ARGUMENTS", new String[]{
                "-c",
                "echo 'Portable Privacy Vault workspace'; " +
                "echo 'Note: access USB shared storage with: termux-setup-storage'; " +
                "exec bash"
        });
        i.putExtra("com.termux.RUN_COMMAND_WORKDIR",
                "/data/data/com.termux/files/home");
        i.putExtra("com.termux.RUN_COMMAND_BACKGROUND", false);
        try {
            startService(i);
            status.setText("Requested a Termux session.");
        } catch (Exception e) {
            toast("Install Termux (F-Droid) to run a full Linux workspace.");
        }
    }

    private void toast(String msg) {
        Toast.makeText(this, msg, Toast.LENGTH_LONG).show();
    }
}
