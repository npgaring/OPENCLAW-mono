"""Scaffold skill: generates project structure files (package.json, configs, etc.)."""
from __future__ import annotations

import json

from app.skills.base import FileOperation, Skill, SkillContext


class ScaffoldSkill(Skill):
    name = "scaffold"
    phase = 1
    depends_on: list[str] = []

    async def generate(self, ctx: SkillContext) -> list[FileOperation]:
        files: list[FileOperation] = []

        package_json = {
            "name": ctx.repo_name,
            "version": "0.1.0",
            "private": True,
            "scripts": {
                "dev": "next dev",
                "build": "next build",
                "start": "next start",
                "lint": "next lint",
            },
            "dependencies": {
                "next": "^15.0.0",
                "react": "^19.0.0",
                "react-dom": "^19.0.0",
                "clsx": "^2.1.0",
                "tailwind-merge": "^2.6.0",
            },
            "devDependencies": {
                "@types/node": "^22.0.0",
                "@types/react": "^19.0.0",
                "@types/react-dom": "^19.0.0",
                "typescript": "^5.8.0",
                "tailwindcss": "^4.2.0",
                "@tailwindcss/postcss": "^4.2.0",
                "postcss": "^8.5.0",
                "eslint": "^9.0.0",
                "eslint-config-next": "^15.0.0",
            },
        }
        files.append(FileOperation(
            path="package.json",
            content=json.dumps(package_json, indent=2),
            file_type="config",
        ))

        tsconfig = {
            "compilerOptions": {
                "target": "ES2017",
                "lib": ["dom", "dom.iterable", "esnext"],
                "allowJs": True,
                "skipLibCheck": True,
                "strict": True,
                "noEmit": True,
                "esModuleInterop": True,
                "module": "esnext",
                "moduleResolution": "bundler",
                "resolveJsonModule": True,
                "isolatedModules": True,
                "jsx": "preserve",
                "incremental": True,
                "plugins": [{"name": "next"}],
                "paths": {"@/*": ["./src/*"]},
            },
            "include": ["next-env.d.ts", "**/*.ts", "**/*.tsx", ".next/types/**/*.ts"],
            "exclude": ["node_modules"],
        }
        files.append(FileOperation(
            path="tsconfig.json",
            content=json.dumps(tsconfig, indent=2),
            file_type="config",
        ))

        next_config = (
            'import type { NextConfig } from "next";\n\n'
            "const nextConfig: NextConfig = {\n"
            "  reactStrictMode: true,\n"
            "};\n\n"
            "export default nextConfig;\n"
        )
        files.append(FileOperation(
            path="next.config.ts",
            content=next_config,
            file_type="config",
        ))

        postcss_config = (
            'const config = {\n'
            '  plugins: {\n'
            '    "@tailwindcss/postcss": {},\n'
            '  },\n'
            '};\n\n'
            'export default config;\n'
        )
        files.append(FileOperation(
            path="postcss.config.mjs",
            content=postcss_config,
            file_type="config",
        ))

        gitignore = (
            "node_modules/\n.next/\nout/\n.env*.local\n"
            "*.tsbuildinfo\nnext-env.d.ts\n"
        )
        files.append(FileOperation(
            path=".gitignore",
            content=gitignore,
            file_type="config",
        ))

        env_example = "# Environment variables\nNEXT_PUBLIC_SITE_URL=\n"
        for integration in ctx.build_sot.integrations:
            key = integration.upper().replace("-", "_").replace(" ", "_")
            env_example += f"NEXT_PUBLIC_{key}_KEY=\n"
        files.append(FileOperation(
            path=".env.example",
            content=env_example,
            file_type="config",
        ))

        for op in files:
            ctx.upstream_files[op.path] = op.content

        return files
