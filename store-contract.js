/* Static preflight only. The generated installer independently verifies every byte and the device. */
(function (root) {
  'use strict';
  const SCHEMA = 'rapp-application/2.0';
  const FEATURES = Object.freeze(['portable-agents/1', 'owned-files/1', 'state-seeds/1', 'local-docker/1']);
  const PARAMETER_FIELDS = new Set([
    'type', 'description', 'enum', 'default', 'minLength', 'maxLength', 'minimum', 'maximum',
    'minItems', 'maxItems', 'uniqueItems', 'format', 'items', 'properties', 'required', 'additionalProperties',
  ]);
  const GRAIL = Object.freeze({
    repo: 'microsoft/aibast-agents-library',
    commit: 'c60521e2cacbcbfa585a118c1275093d7bb15b74',
    version: '0.6.16',
  });
  const SHA256 = /^[0-9a-f]{64}$(?![\s\S])/;
  const documentNames = ['application.schema.json', 'local-docker.schema.json', 'desktop.schema.json'];
  let documents = null;
  let loading = null;
  if (typeof module !== 'undefined' && module.exports) {
    documents = Object.fromEntries(documentNames.map(name => [name, require('./schemas/' + name)]));
  }

  async function ready() {
    if (documents) return;
    if (!loading) {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), 5000);
      loading = Promise.all(documentNames.map(async name => {
        const response = await fetch('./schemas/' + name, {credentials: 'omit', signal: controller.signal});
        if (!response.ok) throw new Error('Contract schemas are unavailable; refusing feature downgrade.');
        return [name, parseJSON(await response.text())];
      })).then(values => { documents = Object.fromEntries(values); }).catch(error => {
        controller.abort();
        loading = null;
        throw error;
      }).finally(() => clearTimeout(timer));
    }
    await loading;
  }

  const object = value => value !== null && typeof value === 'object' && !Array.isArray(value);
  const equal = (a, b) => {
    if (a === b) return true;
    if (Array.isArray(a) && Array.isArray(b)) return a.length === b.length && a.every((v, i) => equal(v, b[i]));
    return object(a) && object(b) && Object.keys(a).length === Object.keys(b).length
      && Object.keys(a).every(key => Object.hasOwn(b, key) && equal(a[key], b[key]));
  };
  const canonicalKey = value => Array.isArray(value) ? '[' + value.map(canonicalKey).join(',') + ']'
    : object(value) ? '{' + Object.keys(value).sort().map(key =>
      JSON.stringify(key) + ':' + canonicalKey(value[key])).join(',') + '}' : JSON.stringify(value);
  const safePath = value => typeof value === 'string' && value.length > 0 && Array.from(value).length <= 512
    && /^[\x20-\x7e]+$(?![\s\S])/.test(value) && !/[\\:]/.test(value)
    && value.split('/').every(part => part && !part.startsWith('.') && !/[ .]$/.test(part));
  const runtimeMatches = value => equal(value, GRAIL);

  function schemaErrors(value, schema, documentName, path = '$', depth = 0) {
    if (depth > 512) return [path + ': declaration nesting exceeds the bound'];
    if (schema === true) return [];
    if (schema === false) return [path + ': declaration is not supported'];
    if (!object(schema)) return [path + ': unsupported schema'];
    const errors = [];
    const check = (v, s, suffix = '') => schemaErrors(v, s, documentName, path + suffix, depth + 1);
    if (schema.$ref) {
      const [file, fragment = ''] = schema.$ref.split('#');
      const targetName = file ? file.split('/').pop() : documentName;
      let target = documents && documents[targetName];
      for (const part of fragment.split('/').slice(1)) {
        target = target && target[part.replace(/~1/g, '/').replace(/~0/g, '~')];
      }
      if (!target) return [path + ': referenced schema is unavailable'];
      errors.push(...schemaErrors(value, target, targetName, path, depth + 1));
    }
    if ('const' in schema && !equal(value, schema.const)) errors.push(path + ': unsupported fixed value');
    if (schema.enum && !schema.enum.some(item => equal(item, value))) errors.push(path + ': unsupported enum value');
    const matches = type => {
      if (type === 'object') return object(value);
      if (type === 'array') return Array.isArray(value);
      if (type === 'null') return value === null;
      if (type === 'integer') return typeof value === 'number' && Number.isSafeInteger(value);
      if (type === 'number') return typeof value === 'number' && Number.isFinite(value);
      return typeof value === type;
    };
    if (schema.type && !(Array.isArray(schema.type) ? schema.type : [schema.type]).some(matches)) {
      errors.push(path + ': invalid type');
      return errors;
    }
    if (schema.allOf) for (const part of schema.allOf) errors.push(...check(value, part));
    if (schema.anyOf && !schema.anyOf.some(part => !check(value, part).length)) errors.push(path + ': no supported shape');
    if (schema.oneOf && schema.oneOf.filter(part => !check(value, part).length).length !== 1) errors.push(path + ': no unique supported shape');
    if (schema.not && !check(value, schema.not).length) errors.push(path + ': forbidden declaration');
    if (schema.if) {
      const branch = check(value, schema.if).length ? schema.else : schema.then;
      if (branch) errors.push(...check(value, branch));
    }
    if (object(value)) {
      const keys = Object.keys(value);
      const properties = schema.properties || {};
      if (schema.minProperties != null && keys.length < schema.minProperties) errors.push(path + ': missing properties');
      if (schema.maxProperties != null && keys.length > schema.maxProperties) errors.push(path + ': too many properties');
      for (const key of schema.required || []) if (!Object.hasOwn(value, key)) errors.push(path + ': missing ' + key);
      for (const key of keys) {
        if (schema.propertyNames) errors.push(...check(key, schema.propertyNames, '.<key>'));
        if (Object.hasOwn(properties, key)) errors.push(...check(value[key], properties[key], '.' + key));
        else if (schema.additionalProperties === false) errors.push(path + ': unsupported field ' + key);
        else if (object(schema.additionalProperties)) errors.push(...check(value[key], schema.additionalProperties, '.' + key));
      }
    } else if (Array.isArray(value)) {
      if (schema.minItems != null && value.length < schema.minItems) errors.push(path + ': too few items');
      if (schema.maxItems != null && value.length > schema.maxItems) errors.push(path + ': too many items');
      if (schema.uniqueItems && new Set(value.map(canonicalKey)).size !== value.length) errors.push(path + ': duplicate items');
      if (schema.contains && !value.some(item => !check(item, schema.contains).length)) errors.push(path + ': missing required item');
      if (schema.items) value.forEach((item, i) => errors.push(...check(item, schema.items, '[' + i + ']')));
    } else if (typeof value === 'string') {
      const length = Array.from(value).length;
      if (schema.minLength != null && length < schema.minLength) errors.push(path + ': text too short');
      if (schema.maxLength != null && length > schema.maxLength) errors.push(path + ': text too long');
      if (schema.pattern && !new RegExp(schema.pattern).test(value)) errors.push(path + ': invalid format');
    } else if (typeof value === 'number') {
      if (schema.minimum != null && value < schema.minimum) errors.push(path + ': below minimum');
      if (schema.maximum != null && value > schema.maximum) errors.push(path + ': above maximum');
      if (schema.exclusiveMinimum != null && value <= schema.exclusiveMinimum) errors.push(path + ': below exclusive minimum');
    }
    return errors;
  }

  function validate(manifest) {
    if (!object(manifest)) return ['E_CONTRACT: Manifest must be an object.'];
    if (manifest.schema === 'rapp-application/1.0') {
      if ('local_docker' in manifest || 'requires' in manifest
          && (!Array.isArray(manifest.requires) || manifest.requires.length)) {
        return ['E_UNSUPPORTED_REQUIREMENT: Mandatory features require a complete application contract.'];
      }
      if (!documents) return ['E_CONTRACT: Contract schemas are unavailable; no partial fallback.'];
      return schemaErrors(manifest, documents['application.schema.json'].$defs.simple, 'application.schema.json');
    }
    if (manifest.schema !== SCHEMA) return ['E_MANIFEST_SCHEMA: Unsupported application schema.'];
    if (!Array.isArray(manifest.requires) || manifest.requires.some(feature => !FEATURES.includes(feature))) {
      return ['E_UNSUPPORTED_REQUIREMENT: Unknown or malformed mandatory features.'];
    }
    if (!documents) return ['E_CONTRACT: Contract schemas are unavailable; no partial fallback.'];
    const errors = schemaErrors(manifest, documents['application.schema.json'].$defs.application, 'application.schema.json');
    if (errors.length) return errors;
    const files = manifest.files;
    const names = Object.keys(files);
    const folded = names.map(name => name.toLowerCase());
    if (new Set(folded).size !== folded.length) errors.push('E_CLOSURE: Case-insensitive file collision.');
    for (const name of names) {
      if (!safePath(name) || ['manifest.json', 'index_entry.json'].includes(name)
          || ['eggs', 'versions', '__pycache__'].includes(name.split('/')[0])) errors.push('E_CLOSURE: Forbidden file path.');
      const parts = name.split('/');
      if (parts.some((part, i) => i < parts.length - 1 && Object.hasOwn(files, parts.slice(0, i + 1).join('/')))) {
        errors.push('E_CLOSURE: A file cannot also be a directory.');
      }
    }
    if (!manifest.agents.includes(manifest.agent)) errors.push('E_NO_ENTRYPOINT: Agent must name a declared entrypoint.');
    const destinations = [];
    for (const name of manifest.agents) {
      const leaf = name.split('/').pop();
      if (!Object.hasOwn(files, name) || !/^[A-Za-z_][A-Za-z0-9_]*_agent\.py$/.test(leaf) || leaf === 'basic_agent.py') {
        errors.push('E_AGENT: Pin every portable agent entrypoint.');
      }
      destinations.push(leaf.toLowerCase());
    }
    if (new Set(destinations).size !== destinations.length) errors.push('E_AGENT: Agent destination collision.');
    for (const field of ['ui', 'service']) if (manifest[field] && !Object.hasOwn(files, manifest[field])) errors.push('E_CLOSURE: Unlocked ' + field + '.');
    for (const source of Object.values(manifest.state.seeds)) if (!Object.hasOwn(files, source)) errors.push('E_CLOSURE: Unlocked state seed.');
    for (const service of manifest.services) if (!Object.hasOwn(files, service.definition)) errors.push('E_CLOSURE: Unlocked service definition.');
    if (manifest.local_docker) {
      const local = manifest.local_docker;
      for (const field of ['component_lock', 'requirements_file', 'jobs_file', 'state_lifecycle_file']) {
        if (!Object.hasOwn(files, local[field])) errors.push('E_CLOSURE: Unlocked ' + field + '.');
      }
      if (!Object.hasOwn(files, local.readiness.live_results)) errors.push('E_CLOSURE: Unlocked readiness evidence.');
      if (local.loader.entrypoint !== manifest.agent || manifest.agents.length !== 1
          || !Object.hasOwn(files, local.loader.descriptor)
          || !Object.hasOwn(files, local.loader.support + 'SCOTTY_CAPABILITY_LOCK.json')) errors.push('E_LOADER: Incomplete revision layout.');
      if (!manifest.requires.includes('owned-files/1')) errors.push('E_UNSUPPORTED_REQUIREMENT: Local layout requires owned-files/1.');
    }
    return errors;
  }

  function parseJSON(text) {
    if (typeof text !== 'string') text = new TextDecoder('utf-8', {fatal: true}).decode(text);
    let pos = 0;
    const whitespace = () => { while (/[ \t\r\n]/.test(text[pos] || '') && pos < text.length) pos++; };
    function value(depth = 0) {
      if (depth > 128) throw new Error('JSON nesting exceeds the bound.');
      whitespace();
      if (text[pos] === '"') {
        const start = pos++;
        while (pos < text.length) {
          if (text[pos] === '\\') { pos += 2; continue; }
          if (text[pos++] === '"') return JSON.parse(text.slice(start, pos));
        }
        throw new Error('Unterminated JSON string.');
      }
      if (text[pos] === '{') {
        const result = Object.create(null);
        const keys = new Set();
        pos++; whitespace();
        if (text[pos] === '}') { pos++; return result; }
        while (pos < text.length) {
          whitespace();
          if (text[pos] !== '"') throw new Error('JSON object keys must be strings.');
          const key = value(depth + 1);
          if (keys.has(key)) throw new Error('Duplicate JSON field: ' + key);
          keys.add(key); whitespace();
          if (text[pos++] !== ':') throw new Error('Invalid JSON object.');
          result[key] = value(depth + 1); whitespace();
          const separator = text[pos++];
          if (separator === '}') return result;
          if (separator !== ',') throw new Error('Invalid JSON object separator.');
        }
      } else if (text[pos] === '[') {
        const result = [];
        pos++; whitespace();
        if (text[pos] === ']') { pos++; return result; }
        while (pos < text.length) {
          result.push(value(depth + 1)); whitespace();
          const separator = text[pos++];
          if (separator === ']') return result;
          if (separator !== ',') throw new Error('Invalid JSON array separator.');
        }
      } else {
        const match = text.slice(pos).match(/^(?:true|false|null|-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?)/);
        if (match) {
          pos += match[0].length;
          const result = JSON.parse(match[0]);
          if (typeof result === 'number' && !Number.isFinite(result)) throw new Error('Non-finite JSON value.');
          return result;
        }
      }
      throw new Error('Invalid JSON.');
    }
    const result = value();
    whitespace();
    if (pos !== text.length) throw new Error('Trailing JSON data.');
    return result;
  }

  async function validateMaterializer(manifest, files, lock) {
    const errors = [];
    const prefix = manifest.local_docker.loader.support;
    const definitions = documents['local-docker.schema.json'].$defs;
    const internal = prefix + 'deploy/local/components.lock.json';
    const publicHosts = new Set([
      'github.com', 'codeload.github.com', 'objects.githubusercontent.com',
      'release-assets.githubusercontent.com', 'raw.githubusercontent.com',
      'files.pythonhosted.org', 'registry.npmjs.org', 'deb.debian.org',
      'huggingface.co', 'cdn-lfs.huggingface.co', 'cdn-lfs-us-1.huggingface.co',
      'cas-bridge.xethub.hf.co', 'download-r2.pytorch.org',
    ]);
    const text = bytes => new TextDecoder('utf-8', {fatal: true}).decode(bytes);
    const sha256 = async bytes => Array.from(new Uint8Array(
      await crypto.subtle.digest('SHA-256', bytes)), byte => byte.toString(16).padStart(2, '0')).join('');
    const canonical = value => new TextEncoder().encode(canonicalKey(value).replace(/[^\x00-\x7f]/g,
      character => '\\u' + character.charCodeAt(0).toString(16).padStart(4, '0')) + '\n');
    if (!files[internal] || manifest.files[internal] !== manifest.files[manifest.local_docker.component_lock]) {
      errors.push('E_COMPONENTS: Root materializer lock must match the scoped runtime lock.');
    }
    function publicUrl(value) {
      try {
        const url = new URL(value);
        if (url.protocol !== 'https:' || !publicHosts.has(url.hostname) || url.username || url.password
            || url.port && url.port !== '443' || url.hash || /[\u0000-\u001f]/.test(value)) throw new Error();
      } catch { errors.push('E_COMPONENTS: Unsupported public artifact origin.'); }
    }
    function registry(reference) {
      const repository = reference.split('@')[0], first = repository.split('/')[0];
      if (repository.includes('/') && (first.includes('.') || first.includes(':') || first === 'localhost')
          && !['ghcr.io', 'docker.io', 'registry-1.docker.io'].includes(first)) errors.push('E_COMPONENTS: Non-public registry.');
    }
    function lockedFiles(items) {
      const selected = new Map();
      for (const item of items) {
        const name = prefix + item.path;
        if (!files[name] || files[name].byteLength !== item.bytes || manifest.files[name] !== item.sha256
            || selected.has(item.target)) errors.push('E_CLOSURE: Missing, changed or colliding recipe input.');
        selected.set(item.target, name);
      }
      return selected;
    }
    for (const artifact of Object.values(lock.artifacts)) publicUrl(artifact.url);
    const groups = new Map();
    for (const [id, group] of Object.entries(lock.input_sets)) {
      publicUrl(group.source.url);
      const selected = lockedFiles(group.files);
      groups.set(id, {group, selected, digest: await sha256(canonical(group))});
      for (const dependency of group.dependencies) {
        const name = selected.get(dependency.manifest);
        if (!name || !files[name]) { errors.push('E_CLOSURE: Missing dependency manifest.'); continue; }
        try {
          if (files[name].byteLength > 4 * 1024 * 1024) throw new Error('Dependency metadata exceeds 4 MiB.');
          const document = parseJSON(files[name]);
          const invalid = schemaErrors(document, definitions.dependencyDocument, 'local-docker.schema.json', name);
          errors.push(...invalid);
          if (invalid.length) continue;
          if (document.artifact_count != null && document.artifact_count !== document.artifacts.length) {
            errors.push('E_COMPONENTS: Dependency artifact count differs.');
          }
          for (const artifact of document.artifacts) {
            publicUrl(artifact.url);
            if (dependency.kind === 'npm') {
              if (!/^[0-9a-f]{128}$(?![\s\S])/.test(artifact.sha512_hex || '')) {
                errors.push('E_COMPONENTS: NPM dependencies require SHA-512 pins.');
              } else {
                const encoded = btoa(artifact.sha512_hex.match(/../g).map(pair =>
                  String.fromCharCode(parseInt(pair, 16))).join(''));
                if (artifact.integrity !== 'sha512-' + encoded) errors.push('E_COMPONENTS: Inconsistent NPM integrity.');
              }
            } else if (!SHA256.test(artifact.sha256 || '')
                || !safePath(artifact[dependency.kind === 'models' ? 'path' : 'filename'])) {
              errors.push('E_COMPONENTS: Dependency digest/path is missing.');
            }
          }
        } catch (error) { errors.push('E_COMPONENTS: Invalid dependency declaration: ' + error.message); }
      }
    }
    const environments = new Set();
    for (const [id, component] of Object.entries(lock.components)) {
      if (environments.has(component.env)) errors.push('E_COMPONENTS: Duplicate image environment.');
      environments.add(component.env);
      if (!lock.profile.guest_platforms.includes(component.platform)) errors.push('E_COMPONENTS: Guest architecture is not declared.');
      if (component.kind === 'registry') registry(component.reference);
      if (component.recipe?.bases) component.recipe.bases.forEach(registry);
      if (component.kind === 'dockerfile') {
        const selected = lockedFiles(component.recipe.files);
        const dockerfile = selected.get('Dockerfile');
        if (!dockerfile || !files[dockerfile]) errors.push('E_CLOSURE: A locked Dockerfile is required.');
        else {
          const contents = text(files[dockerfile]);
          const bases = Array.from(contents.matchAll(/^FROM\s+([^\s]+)/gim), match => match[1]);
          if (!equal(bases, component.recipe.bases) || /^\s*ADD\s|^\s*#\s*syntax=/im.test(contents)) {
            errors.push('E_COMPONENTS: Dockerfile base or remote input differs from its declaration.');
          }
        }
        const targets = new Set(selected.keys());
        for (const artifact of component.recipe.artifacts) {
          if (!Object.hasOwn(lock.artifacts, artifact.artifact) || targets.has(artifact.target)) {
            errors.push('E_COMPONENTS: Missing or colliding recipe artifact.');
          }
          targets.add(artifact.target);
        }
      }
      if (component.kind === 'openshorts-offline') {
        const selected = groups.get(component.recipe.input_set);
        if (!selected || selected.digest !== component.recipe.input_set_sha256) errors.push('E_COMPONENTS: Input-set digest differs.');
        const derived = 'generated/dockerfiles/' + id + '.Dockerfile';
        if (!files[derived] || manifest.files[derived] !== component.recipe.dockerfile_sha256) {
          errors.push('E_CLOSURE: Missing or changed derived public Dockerfile.');
        } else {
          const contents = text(files[derived]);
          const bases = Array.from(contents.matchAll(/^FROM\s+([^\s]+)/gim), match => match[1]);
          if (!equal(bases, component.recipe.bases) || /^\s*ADD\s|^\s*#\s*syntax=/im.test(contents)) {
            errors.push('E_COMPONENTS: Derived Dockerfile base or remote input differs.');
          }
        }
      }
    }
    for (const services of Object.values(lock.applications)) {
      if (Object.values(services).some(id => !Object.hasOwn(lock.components, id))) errors.push('E_COMPONENTS: Unknown application component.');
    }
    return errors;
  }

  async function validateReferences(manifest, files) {
    const manifestErrors = validate(manifest);
    if (manifestErrors.length) return manifestErrors;
    if (!manifest.local_docker) return [];
    const local = manifest.local_docker;
    const declarations = [
      [local.component_lock, 'componentLock'], [local.requirements_file, 'hostProfiles'],
      [local.jobs_file, 'jobContracts'], [local.state_lifecycle_file, 'stateLifecycle'],
      [local.readiness.live_results, 'evidence'], [local.loader.descriptor, 'loaderDescriptor'],
    ];
    const errors = [];
    const values = Object.create(null);
    for (const [name, definition] of declarations) {
      const schema = documents['local-docker.schema.json'].$defs[definition];
      if (!schema) { errors.push('E_CONTRACT: Unsupported referenced declaration: ' + definition); continue; }
      try {
        if (files[name].byteLength > 256 * 1024) throw new Error('Referenced declaration exceeds 256 KiB.');
        const parsed = parseJSON(files[name]);
        values[definition] = parsed;
        errors.push(...schemaErrors(parsed, schema, 'local-docker.schema.json', name));
      } catch (error) { errors.push('E_CONTRACT: ' + name + ': ' + error.message); }
    }
    if (errors.length) return errors;
    const loader = values.loaderDescriptor;
    const prefix = local.loader.support;
    if (loader.entrypoint_sha256 !== manifest.files[local.loader.entrypoint]
        || prefix !== 'singleton/scotty_support_' + loader.support_sha256 + '/'
        || manifest.agents.length !== 1) errors.push('E_LOADER: Descriptor and complete loader layout disagree.');
    const lockName = prefix + 'SCOTTY_CAPABILITY_LOCK.json';
    if (!Object.hasOwn(files, lockName) || manifest.files[lockName] !== loader.support_sha256) {
      errors.push('E_LOADER: Missing or mismatched support inventory.');
    } else {
      try {
        const lock = parseJSON(files[lockName]);
        const invalid = schemaErrors(lock, documents['local-docker.schema.json'].$defs.supportLock,
          'local-docker.schema.json', lockName);
        errors.push(...invalid);
        if (!invalid.length) {
          const members = lock.files.map(item => prefix + item.path);
          if (new Set(members).size !== members.length
              || !members.includes(prefix + 'agents/scotty_agent.py')
              || lock.files.some(item => item.path === 'brainstem.py')
              || !equal([...members, lockName].sort(), Object.keys(files).filter(name => name.startsWith(prefix)).sort())) {
            errors.push('E_LOADER: Support inventory is not the complete subtree.');
          }
          for (const item of lock.files) {
            const name = prefix + item.path;
            if (!Object.hasOwn(files, name) || files[name].byteLength !== item.bytes
                || manifest.files[name] !== item.sha256) errors.push('E_LOADER: Support member differs from its inventory.');
          }
        }
      } catch (error) { errors.push('E_LOADER: Invalid support inventory: ' + error.message); }
    }
    const materializer = values.componentLock.schema === 'rapp-dock-components/1';
    const components = materializer ? [] : values.componentLock.components;
    const componentIds = new Set(materializer ? Object.keys(values.componentLock.applications) : components.map(component => component.id));
    if (!materializer && componentIds.size !== components.length) errors.push('E_COMPONENTS: Duplicate component identity.');
    if (materializer) errors.push(...await validateMaterializer(manifest, files, values.componentLock));
    const sourceSafe = source => {
      try {
        const url = new URL(source.url);
        return url.protocol === 'https:' && !url.username && !url.password && !/[\s@]/.test(source.url)
          && !url.search && !url.hash && !url.port
          && !/^(?:localhost|\[|[0-9]+(?:\.|$))/.test(url.hostname)
          && !/\.(?:localhost|local|internal)$/.test(url.hostname);
      } catch { return false; }
    };
    for (const component of components) {
      for (const source of [component.source, ...component.inputs]) {
        if (!sourceSafe(source)) errors.push('E_COMPONENTS: Source inputs require credential-free public HTTPS URLs.');
        if (values.componentLock.mode === 'locked'
            && (!source.revision || !source.bytes || !SHA256.test(source.sha256))) errors.push('E_COMPONENTS: Locked source inputs must have complete immutable pins.');
      }
      if (component.dependencies.some(id => !componentIds.has(id) || id === component.id)) errors.push('E_COMPONENTS: Unresolved component dependency.');
      for (const image of component.images) {
        if (image.build_recipe && !Object.hasOwn(manifest.files, image.build_recipe)) errors.push('E_CLOSURE: Unlocked image recipe.');
        if (values.componentLock.mode === 'locked' && !image.reference && !image.build_recipe) errors.push('E_COMPONENTS: Missing image digest or locked build recipe.');
      }
      for (const name of component.licenses.files) if (!Object.hasOwn(manifest.files, name)) errors.push('E_CLOSURE: Unlocked license input.');
    }
    const visiting = new Set();
    const visited = new Set();
    const byId = new Map(components.map(component => [component.id, component]));
    function visit(id) {
      if (visiting.has(id)) return false;
      if (visited.has(id) || !byId.has(id)) return true;
      visiting.add(id);
      if (!byId.get(id).dependencies.every(visit)) return false;
      visiting.delete(id); visited.add(id);
      return true;
    }
    if (!components.every(component => visit(component.id))) errors.push('E_COMPONENTS: Cyclic component dependencies.');
    const jobs = values.jobContracts.jobs;
    const jobIds = new Set(jobs.map(job => job.id));
    if (jobIds.size !== jobs.length) errors.push('E_JOBS: Duplicate job identity.');
    function parameter(spec, depth = 0) {
      if (depth > 32) { errors.push('E_JOBS: Job schema nesting exceeds the bound.'); return; }
      if (Object.keys(spec).some(key => !PARAMETER_FIELDS.has(key))) {
        errors.push('E_UNSUPPORTED_REQUIREMENT: Unsupported job-parameter constraint.');
        return;
      }
      const properties = spec.properties || {};
      if (spec.type === 'object' && (spec.additionalProperties !== false || !object(spec.properties)
          || !Array.isArray(spec.required) || spec.required.some(key => !Object.hasOwn(properties, key)))) {
        errors.push('E_JOBS: Object inputs require closed properties and declared required fields.');
      }
      if (spec.type === 'array' && !spec.items) errors.push('E_JOBS: Array inputs require typed items.');
      function runtimeShape(source) {
        const result = Object.fromEntries(Object.entries(source).filter(([key]) => PARAMETER_FIELDS.has(key)));
        if (object(result.properties)) result.properties = Object.fromEntries(
          Object.entries(result.properties).map(([key, child]) => [key, runtimeShape(child)]));
        if (result.items) result.items = runtimeShape(result.items);
        return result;
      }
      if ('default' in spec && schemaErrors(spec.default, runtimeShape(spec), 'local-docker.schema.json').length) errors.push('E_JOBS: Default does not satisfy its parameter type.');
      if (spec.items) parameter(spec.items, depth + 1);
      for (const child of Object.values(properties)) parameter(child, depth + 1);
    }
    for (const job of jobs) {
      if (!componentIds.has(job.application) || !job.id.startsWith(job.application + '.')) errors.push('E_JOBS: Job does not belong to a declared component.');
      if (job.providers.includes('copilot') && !componentIds.has('intelligence')) errors.push('E_JOBS: Copilot requires the intelligence component.');
      parameter(job.input_schema);
    }
    for (const [id, claim] of Object.entries(local.readiness.jobs || {})) {
      if (!jobs.some(job => job.id === id && job.mode === claim.mode)) errors.push('E_READINESS: Unknown job or mode claim.');
    }
    for (const result of values.evidence.results) {
      const job = jobs.find(item => item.id === result.job);
      if (!job || job.mode !== result.mode) errors.push('E_READINESS: Evidence does not identify a declared job/mode.');
    }
    const profiles = values.hostProfiles.profiles;
    if (new Set(profiles.map(profile => profile.id)).size !== profiles.length) errors.push('E_REQUIREMENTS: Duplicate host profile.');
    for (const [id, status] of Object.entries(local.readiness.fresh_install_profiles || {})) {
      if (!profiles.some(profile => profile.id === id && profile.fresh_install === status)) errors.push('E_READINESS: Host-profile installation facts disagree.');
    }
    for (const app of ['dify', 'openshorts']) {
      if (local.readiness.recreation[app] !== 'passed' && values.stateLifecycle.retention[app] !== 'stop-retain') {
        errors.push('E_STATE: Unqualified recreation must retain container layers.');
      }
    }
    if (values.componentLock.mode === 'template' || values.evidence.synthetic) {
      if (local.readiness.candidate !== 'experimental' || local.readiness.fresh_install !== 'pending'
          || manifest.provenance.deployed || manifest.provenance.job_verified
          || values.evidence.scope !== 'authoring-template' || values.evidence.candidate_digest !== null
          || values.evidence.acceptance_suite_revision !== null || values.evidence.observed_at !== null
          || values.evidence.results.some(result => result.status === 'passed')
          || Object.values(local.readiness.recreation).includes('passed')
          || Object.values(local.readiness.jobs || {}).some(job => job.status === 'passed')) {
        errors.push('E_READINESS: Synthetic authoring material cannot qualify runtime outcomes.');
      }
    } else if (values.evidence.candidate_digest !== loader.support_sha256) {
      errors.push('E_READINESS: Evidence must identify the exact candidate support revision.');
    }
    return errors;
  }

  async function validateFiles(manifest, readFile, paths) {
    const errors = validate(manifest);
    if (errors.length || manifest.schema !== SCHEMA) return errors;
    const names = Object.keys(manifest.files);
    if (paths && (paths.length !== names.length || new Set(paths).size !== paths.length
        || paths.some(name => !Object.hasOwn(manifest.files, name)))) {
      return ['E_CLOSURE: Missing or undeclared application files.'];
    }
    const files = Object.create(null);
    let total = 0;
    for (const name of names) {
      let bytes = await readFile(name);
      if (bytes instanceof ArrayBuffer) bytes = new Uint8Array(bytes);
      if (!(bytes instanceof Uint8Array)) throw new Error('Locked file reader must return bytes.');
      total += bytes.byteLength;
      if (total > 20 * 1024 * 1024) return ['E_PACKAGE_SIZE: Expanded application exceeds 20 MiB.'];
      const hash = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', bytes)),
        byte => byte.toString(16).padStart(2, '0')).join('');
      if (hash !== manifest.files[name]) errors.push('E_FILE_DIGEST: ' + name);
      files[name] = bytes;
    }
    if (!errors.length) errors.push(...await validateReferences(manifest, files));
    return errors;
  }

  function assetUrl(url, kind, hash) {
    if (typeof url !== 'string' || !SHA256.test(hash)) return false;
    const escaped = kind === 'egg' ? '-' + hash + '\\.egg' : '_' + hash + '_hatcher_agent\\.py';
    return new RegExp('^https://raw\\.githubusercontent\\.com/kody-w/(?:RAPP_Store|rapp_store)/(?:main|[0-9a-f]{40})/api/v1/'
      + kind + '/[a-z][a-z0-9_.-]*' + escaped + '$').test(url);
  }

  function canInstall(entry) {
    if (!object(entry) || entry.installable !== true || entry.application?.schema !== SCHEMA || validate(entry.application).length
        || !Array.isArray(entry.install_blockers) || entry.install_blockers.length
        || !runtimeMatches(entry.runtime) || !equal(entry.requires, entry.application.requires)
        || ['id', 'version', 'publisher'].some(key => entry[key] !== entry.application[key])
        || !assetUrl(entry.egg_url, 'egg', entry.package_sha256)
        || !assetUrl(entry.hatcher_url, 'hatcher', entry.hatcher_sha256)) return false;
    const ready = entry.application.local_docker?.readiness;
    return !ready || ready.fresh_install === 'passed' && ready.package_verification === 'passed';
  }

  const contract = Object.freeze({
    SCHEMA, FEATURES, GRAIL, ready, validate, validateFiles, validateReferences,
    parseJSON, safePath, runtimeMatches, canInstall,
  });
  root.RappStoreContract = contract;
  if (typeof module !== 'undefined' && module.exports) module.exports = contract;
})(globalThis);
