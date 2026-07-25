// The Maid — Face Cluster TypeScript types (mirrors backend face_tagger.py)

export interface FaceClusterFace {
  file_id: string;
  file_path: string;
}

export interface FaceClusterInfo {
  cluster_id: number;
  cluster_label: string;   // "Unknown_Person_1" or user-named (e.g. "Sarah")
  face_count: number;
  representative_path: string;
  faces: FaceClusterFace[];
}

export interface RenameResult {
  renamed: number;
  tagged: number;
  skipped: number;
  errors: string[];
}