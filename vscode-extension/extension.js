const vscode = require('vscode');
const fs = require('fs');
const path = require('path');
const os = require('os');

const OUTPUT_PATH = path.join(os.homedir(), '.capsule', 'vscode-open-files.json');

function writeOpenFiles() {
    const files = [];
    for (const group of vscode.window.tabGroups.all) {
        for (const tab of group.tabs) {
            if (tab.input instanceof vscode.TabInputText) {
                files.push(tab.input.uri.fsPath);
            }
        }
    }
    const data = {
        files,
        updated_at: new Date().toISOString(),
        workspaceFolders: (vscode.workspace.workspaceFolders || []).map(f => f.uri.fsPath),
    };
    fs.mkdirSync(path.dirname(OUTPUT_PATH), { recursive: true });
    fs.writeFileSync(OUTPUT_PATH, JSON.stringify(data, null, 2));
}

function activate(context) {
    writeOpenFiles();
    context.subscriptions.push(
        vscode.window.tabGroups.onDidChangeTabs(() => writeOpenFiles())
    );
}

function deactivate() {}

module.exports = { activate, deactivate };
