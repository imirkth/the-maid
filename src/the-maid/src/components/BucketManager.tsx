import { useState } from "react";

interface Bucket {
  id: string;
  name: string;
  path: string;
}

export default function BucketManager() {
  const [buckets, setBuckets] = useState<Bucket[]>([
    { id: "1", name: "Desktop", path: "~/Desktop" },
    { id: "2", name: "Documents", path: "~/Documents" },
    { id: "3", name: "Pictures", path: "~/Pictures" },
    { id: "4", name: "Downloads", path: "~/Downloads" },
  ]);
  const [newName, setNewName] = useState("");
  const [newPath, setNewPath] = useState("");

  const addBucket = () => {
    if (!newName || !newPath) return;
    const id = Date.now().toString();
    setBuckets([...buckets, { id, name: newName, path: newPath }]);
    setNewName("");
    setNewPath("");
  };

  const removeBucket = (id: string) => {
    setBuckets(buckets.filter((b) => b.id !== id));
  };

  return (
    <div className="bucket-manager">
      <h2>📂 Bucket Manager</h2>
      <p>These are the approved destination folders for file organization.</p>

      <ul className="bucket-list">
        {buckets.map((b) => (
          <li key={b.id} className="bucket-item">
            <div>
              <strong>{b.name}</strong>
              <br />
              <code>{b.path}</code>
            </div>
            <button onClick={() => removeBucket(b.id)} className="danger">
              Remove
            </button>
          </li>
        ))}
      </ul>

      <div className="add-bucket">
        <h3>Add New Bucket</h3>
        <input
          type="text"
          placeholder="Name (e.g., Work Documents)"
          value={newName}
          onChange={(e) => setNewName(e.target.value)}
        />
        <input
          type="text"
          placeholder="Path (e.g., ~/Documents/Work)"
          value={newPath}
          onChange={(e) => setNewPath(e.target.value)}
        />
        <button onClick={addBucket}>Add Bucket</button>
      </div>
    </div>
  );
}
