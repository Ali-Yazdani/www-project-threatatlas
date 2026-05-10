import { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { toast } from 'sonner';
import {
  ReactFlow,
  MiniMap,
  Controls,
  Background,
  useNodesState,
  useEdgesState,
  addEdge,
  type Connection,
  type Edge,
  type Node,
  BackgroundVariant,
  Panel,
  ReactFlowProvider,
  useReactFlow,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { productsApi, diagramsApi, diagramThreatsApi, diagramMitigationsApi } from '@/lib/api';
import { useAuth } from '@/contexts/AuthContext';
import { Button } from '@/components/ui/button';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Card, CardContent } from '@/components/ui/card';
import {
  Plus,
  Save,
  Cpu,
  Database,
  Users,
  Box as BoxIcon,
  Trash2,
  Grid3x3,
  History,
  Package,
  ChevronRight,
  Download,
  MessageSquare,
  Pencil,
  Maximize,
  Minimize,
  Sparkles,
  Upload,
  Home,
} from 'lucide-react';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import DiagramNode from '@/components/DiagramNode';
import ElementPropertiesSheet from '@/components/ElementPropertiesSheet';
import DiagramVersionHistory from '@/components/DiagramVersionHistory';
import DiagramVersionComparison from '@/components/DiagramVersionComparison';
import ModelSelector from '@/components/ModelSelector';
import { ImportDrawioButton } from '@/components/ImportDrawioButton';
import AIChatSheet from '@/components/AIChatSheet';

interface Product {
  id: number;
  name: string;
}

interface Diagram {
  id: number;
  product_id: number;
  name: string;
  diagram_data: any;
}

const nodeTypes = {
  custom: DiagramNode,
};

export function DiagramsContent() {
  const { canWrite } = useAuth();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const productId = searchParams.get('product');
  const diagramId = searchParams.get('diagram');

  const [products, setProducts] = useState<Product[]>([]);
  const [selectedProduct, setSelectedProduct] = useState<number | null>(null);
  const [diagrams, setDiagrams] = useState<Diagram[]>([]);
  const [selectedDiagram, setSelectedDiagram] = useState<number | null>(null);
  const [diagramName, setDiagramName] = useState('');
  const [saving, setSaving] = useState(false);

  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const { fitView, getNodes } = useReactFlow();

  // ── Boundary attach state ──────────────────────────────────────────────────
  const [dragOverBoundaryId, setDragOverBoundaryId] = useState<string | null>(null);

  const handleExportJson = () => {
    const data = {
      name: diagramName,
      nodes,
      edges,
      productId: selectedProduct,
      exportedAt: new Date().toISOString(),
      version: '1.0'
    };
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `${diagramName.replace(/\s+/g, '_') || 'diagram'}_export.json`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  };

  // ── Create-diagram wizard state ────────────────────────────────────────────
  const [showCreateWizard, setShowCreateWizard] = useState(false);
  const [wizardStep, setWizardStep] = useState<'choose' | 'blank'>('choose');
  const [newDiagramName, setNewDiagramName] = useState('');
  const [creatingBlank, setCreatingBlank] = useState(false);
  const [importDialogOpen, setImportDialogOpen] = useState(false);
  // Import choice (new diagram vs replace current)
  const [showImportChoice, setShowImportChoice] = useState(false);
  const [importMode, setImportMode] = useState<'new' | 'replace'>('new');

  const openCreateWizard = () => {
    setWizardStep('choose');
    setNewDiagramName('');
    setShowCreateWizard(true);
  };

  const handleCreateBlankDiagram = async () => {
    if (!selectedProduct || !newDiagramName.trim()) return;
    try {
      setCreatingBlank(true);
      const response = await diagramsApi.create({
        product_id: selectedProduct,
        name: newDiagramName.trim(),
        diagram_data: { nodes: [], edges: [] },
      });
      setShowCreateWizard(false);
      navigate(`/diagrams?product=${selectedProduct}&diagram=${response.data.id}`);
      loadDiagrams(selectedProduct);
      toast.success('Diagram created successfully.');
    } catch {
      toast.error('Failed to create diagram.');
    } finally {
      setCreatingBlank(false);
    }
  };
  // ── End wizard state ───────────────────────────────────────────────────────

  const [sheetOpen, setSheetOpen] = useState(false);
  const [selectedElement, setSelectedElement] = useState<{ id: string; type: 'node' | 'edge'; label: string; nodeType?: string; description?: string } | null>(null);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [diagramToDelete, setDiagramToDelete] = useState<Diagram | null>(null);

  const [isCreatingModel, setIsCreatingModel] = useState(false);
  const [isEditingModel, setIsEditingModel] = useState(false);
  const [isDeletingModel, setIsDeletingModel] = useState(false);

  // Threat/mitigation count badges per element_id
  const [elementCounts, setElementCounts] = useState<Record<string, { t: number; m: number }>>({});

  const loadElementCounts = async (diagId: number, modelId?: number | null) => {
    try {
      const params: Record<string, number> = { diagram_id: diagId };
      if (modelId) params.model_id = modelId;
      const [threatsRes, mitsRes] = await Promise.all([
        diagramThreatsApi.list(params),
        diagramMitigationsApi.list(params),
      ]);
      const counts: Record<string, { t: number; m: number }> = {};
      for (const dt of threatsRes.data) {
        if (!counts[dt.element_id]) counts[dt.element_id] = { t: 0, m: 0 };
        counts[dt.element_id].t += 1;
      }
      for (const dm of mitsRes.data) {
        if (!counts[dm.element_id]) counts[dm.element_id] = { t: 0, m: 0 };
        counts[dm.element_id].m += 1;
      }
      setElementCounts(counts);
    } catch {
      // non-critical — silently ignore
    }
  };

  // Model state
  const [activeModelId, setActiveModelId] = useState<number | null>(null);
  const [activeModel, setActiveModel] = useState<any>(null);

  // Reload element counts whenever the selected model changes so badges
  // reflect only threats/mitigations belonging to the active model.
  useEffect(() => {
    if (selectedDiagram) {
      loadElementCounts(selectedDiagram, activeModelId);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeModelId, selectedDiagram]);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  const toggleFullscreen = () => {
    if (!document.fullscreenElement) {
      containerRef.current?.requestFullscreen().catch((err) => {
        console.error(`Error attempting to enable fullscreen: ${err.message}`);
        toast.error('Failed to enable fullscreen mode.');
      });
      setIsFullscreen(true);
    } else {
      document.exitFullscreen();
      setIsFullscreen(false);
    }
  };

  useEffect(() => {
    const handleFullscreenChange = () => {
      setIsFullscreen(!!document.fullscreenElement);
    };
    document.addEventListener('fullscreenchange', handleFullscreenChange);
    return () => document.removeEventListener('fullscreenchange', handleFullscreenChange);
  }, []);

  // Version controls
  const [versionComment, setVersionComment] = useState('');
  const [showVersionComment, setShowVersionComment] = useState(false);
  const [versionHistoryOpen, setVersionHistoryOpen] = useState(false);
  const [currentVersion, setCurrentVersion] = useState(0);
  const [compareVersions, setCompareVersions] = useState<{ from: number; to: number } | null>(null);
  const [aiChatOpen, setAiChatOpen] = useState(false);

  useEffect(() => {
    loadProducts();
  }, []);

  useEffect(() => {
    if (productId) {
      setSelectedProduct(parseInt(productId));
    }
  }, [productId]);

  useEffect(() => {
    if (selectedProduct) {
      loadDiagrams(selectedProduct);
    }
  }, [selectedProduct]);

  useEffect(() => {
    if (diagramId) {
      setSelectedDiagram(parseInt(diagramId));
      loadDiagram(parseInt(diagramId));
    }
  }, [diagramId]);

  const loadProducts = async () => {
    try {
      const response = await productsApi.list();
      setProducts(response.data);
    } catch (error) {
      console.error('Error loading products:', error);
      toast.error('Failed to load products.');
    }
  };

  const loadDiagrams = async (prodId: number) => {
    try {
      const response = await diagramsApi.list({ product_id: prodId });
      setDiagrams(response.data);
    } catch (error) {
      console.error('Error loading diagrams:', error);
      toast.error('Failed to load diagrams.');
    }
  };

  const loadDiagram = async (diagId: number) => {
    try {
      const response = await diagramsApi.get(diagId);
      const diagram = response.data;
      setDiagramName(diagram.name);
      setCurrentVersion(diagram.current_version || 0);

      if (diagram.diagram_data) {
        const loadedNodes = (diagram.diagram_data.nodes || []).map((node: Node) => ({
          ...node,
          zIndex: node.data.type === 'boundary' ? -1 : (node.zIndex || 0)
        })).sort((a: Node, b: Node) => (a.zIndex || 0) - (b.zIndex || 0));
        setNodes(loadedNodes);
        setEdges(diagram.diagram_data.edges || []);
      }
      loadElementCounts(diagId, activeModelId);
    } catch (error) {
      console.error('Error loading diagram:', error);
      toast.error('Failed to load diagram.');
    }
  };

  const handleCreateDiagram = async () => {
    if (!selectedProduct) return;

    try {
      const response = await diagramsApi.create({
        product_id: selectedProduct,
        name: 'New Diagram',
        diagram_data: { nodes: [], edges: [] },
      });

      navigate(`/diagrams?product=${selectedProduct}&diagram=${response.data.id}`);
      loadDiagrams(selectedProduct);
      toast.success('Diagram created successfully.');
    } catch (error) {
      console.error('Error creating diagram:', error);
      toast.error('Failed to create diagram.');
    }
  };

  const handleSaveDiagram = async () => {
    if (!selectedDiagram) return;

    try {
      setSaving(true);
      const cleanNodes = nodes.map(({ data: { threatCount: _t, mitigationCount: _m, isDropTarget: _d, ...restData }, ...rest }) => ({
        ...rest,
        data: restData,
      }));
      await diagramsApi.update(selectedDiagram, {
        name: diagramName,
        diagram_data: { nodes: cleanNodes, edges },
        version_comment: versionComment || undefined,
      });

      // Clear version comment after successful save
      setVersionComment('');
      setShowVersionComment(false);

      // Reload diagram to get updated version number
      await loadDiagram(selectedDiagram);
      toast.success('Diagram saved successfully.');
    } catch (error) {
      console.error('Error saving diagram:', error);
      toast.error('Failed to save diagram.');
    } finally {
      setSaving(false);
    }
  };

  const onConnect = useCallback(
    (params: Connection) => setEdges((eds) => addEdge({ ...params, animated: true, label: 'Data Flow' } as Edge, eds)),
    [setEdges]
  );

  // ── Boundary grouping ──────────────────────────────────────────────────────
  // Fixed rendered sizes for non-boundary nodes (used to compute center point)
  const ATTACH_SIZE: Record<string, { w: number; h: number }> = {
    process:   { w: 96,  h: 96  },
    datastore: { w: 140, h: 40  },
    external:  { w: 120, h: 44  },
  };

  const getBoundaryUnder = useCallback((node: Node): Node | undefined => {
    const allNodes = getNodes();
    // Absolute position: child positions are relative to parentId node
    const parent = node.parentId ? allNodes.find(n => n.id === node.parentId) : undefined;
    const absX = (parent ? parent.position.x : 0) + node.position.x;
    const absY = (parent ? parent.position.y : 0) + node.position.y;
    const size = ATTACH_SIZE[node.data.type as string] ?? { w: node.width ?? 80, h: node.height ?? 40 };
    const cx = absX + size.w / 2;
    const cy = absY + size.h / 2;
    return allNodes.find(n => {
      if (n.data.type !== 'boundary' || n.id === node.id) return false;
      const bx = n.position.x; const by = n.position.y;
      const bw = n.width ?? 300; const bh = n.height ?? 200;
      return cx >= bx && cx <= bx + bw && cy >= by && cy <= by + bh;
    });
  }, [getNodes]);

  const onNodeDrag = useCallback((_event: React.MouseEvent, node: Node) => {
    if (node.data.type === 'boundary') { setDragOverBoundaryId(null); return; }
    const boundary = getBoundaryUnder(node);
    setDragOverBoundaryId(boundary?.id ?? null);
  }, [getBoundaryUnder]);

  const onNodeDragStop = useCallback((_event: React.MouseEvent, node: Node) => {
    if (node.data.type === 'boundary') return;
    setDragOverBoundaryId(null);

    const allNodes = getNodes();
    const parent = node.parentId ? allNodes.find(n => n.id === node.parentId) : undefined;
    const absX = (parent ? parent.position.x : 0) + node.position.x;
    const absY = (parent ? parent.position.y : 0) + node.position.y;
    const containingBoundary = getBoundaryUnder(node);

    if (containingBoundary) {
      if (node.parentId === containingBoundary.id) return; // unchanged
      const relPos = { x: absX - containingBoundary.position.x, y: absY - containingBoundary.position.y };
      setNodes(nds => nds.map(n =>
        n.id !== node.id ? n : { ...n, parentId: containingBoundary.id, position: relPos }
      ));
    } else if (node.parentId) {
      // Dragged outside its boundary — detach
      setNodes(nds => nds.map(n => {
        if (n.id !== node.id) return n;
        // eslint-disable-next-line @typescript-eslint/no-unused-vars
        const { parentId: _p, extent: _e, ...rest } = n as any;
        return { ...rest, position: { x: absX, y: absY } };
      }));
    }
  }, [getNodes, getBoundaryUnder, setNodes]);
  // ── End boundary grouping ──────────────────────────────────────────────────

  const addNode = (type: string) => {
    const newNode: Node = {
      id: `${type}-${Date.now()}`,
      type: 'custom',
      position: { x: Math.random() * 300 + 100, y: Math.random() * 300 + 100 },
      data: { label: `New ${type}`, type },
      // Set z-index lower for boundaries so they appear behind other elements
      zIndex: type === 'boundary' ? -1 : 10,
    };
    setNodes((nds) => {
      const nextNodes = [...nds, newNode];
      return nextNodes.sort((a: Node, b: Node) => (a.zIndex || 0) - (b.zIndex || 0));
    });
  };

  const handleNodeClick = (_event: React.MouseEvent, node: Node) => {
    setSelectedElement({
      id: node.id,
      type: 'node',
      label: node.data.label as string,
      nodeType: node.data.type as string,
      description: (node.data.description as string) ?? ''
    });
    setSheetOpen(true);
  };

  const handleEdgeClick = (_event: React.MouseEvent, edge: Edge) => {
    setSelectedElement({
      id: edge.id,
      type: 'edge',
      label: (edge.label as string) || 'Data Flow'
    });
    setSheetOpen(true);
  };

  const handleDeleteElement = () => {
    if (!selectedElement) return;

    if (selectedElement.type === 'node') {
      setNodes((nds) => nds.filter((node) => node.id !== selectedElement.id));
      setEdges((eds) => eds.filter((edge) =>
        edge.source !== selectedElement.id && edge.target !== selectedElement.id
      ));
    } else {
      setEdges((eds) => eds.filter((edge) => edge.id !== selectedElement.id));
    }
    setSheetOpen(false);
    setSelectedElement(null);
  };

  const handleDeleteDiagram = async () => {
    if (!diagramToDelete || !selectedProduct) return;

    try {
      const deletedId = diagramToDelete.id;
      await diagramsApi.delete(deletedId);
      setDiagramToDelete(null);

      // If currently viewing the deleted diagram, navigate back to diagram list
      if (selectedDiagram === deletedId) {
        navigate(`/diagrams?product=${selectedProduct}`);
      }

      loadDiagrams(selectedProduct);
      toast.success('Diagram deleted successfully.');
    } catch (error) {
      console.error('Error deleting diagram:', error);
      toast.error('Failed to delete diagram.');
    }
  };

  const handleVersionRestore = async () => {
    if (!selectedDiagram) return;
    await loadDiagram(selectedDiagram);
    setVersionHistoryOpen(false);
  };

  const handleVersionCompare = (fromVersion: number, toVersion: number) => {
    setCompareVersions({ from: fromVersion, to: toVersion });
    setVersionHistoryOpen(false);
  };

  const handleImportSuccess = (diagramId: number) => {
    if (importMode === 'replace') {
      loadDiagram(diagramId);
    } else {
      loadDiagrams(selectedProduct!);
      navigate(`/diagrams?product=${selectedProduct}&diagram=${diagramId}`);
    }
    setImportMode('new');
  };

  // Merge threat/mitigation counts into node data for rendering only (never saved)
  const nodesWithCounts = useMemo(() =>
    nodes.map(node => ({
      ...node,
      data: {
        ...node.data,
        threatCount: elementCounts[node.id]?.t ?? 0,
        mitigationCount: elementCounts[node.id]?.m ?? 0,
        isDropTarget: node.id === dragOverBoundaryId,
      },
    })),
    [nodes, elementCounts, dragOverBoundaryId]
  );

  const selectedProductData = products.find(p => p.id === selectedProduct);

  if (!selectedProduct) {
    return (
      <div className="flex-1 p-4 md:p-6 lg:p-8">
        <div className="max-w-2xl mx-auto space-y-6">
          <div>
            <h1 className="text-3xl font-medium tracking-tight">Data Flow Diagrams</h1>
            <p className="text-muted-foreground mt-1">
              Create and visualize data flow diagrams for your products
            </p>
          </div>
          <Card>
            <CardContent className="flex flex-col items-center justify-center p-12">
              <Grid3x3 className="h-12 w-12 text-muted-foreground mb-4" />
              <p className="text-lg font-medium mb-2">Select a product to get started</p>
              <p className="text-sm text-muted-foreground mb-6 text-center">
                Choose a product to view and create diagrams
              </p>
              <Select value={selectedProduct?.toString()} onValueChange={(val) => navigate(`/diagrams?product=${val}`)}>
                <SelectTrigger className="w-full max-w-64">
                  <SelectValue placeholder="Select a product" />
                </SelectTrigger>
                <SelectContent>
                  {products.map((product) => (
                    <SelectItem key={product.id} value={product.id.toString()}>
                      {product.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </CardContent>
          </Card>
        </div>
      </div>
    );
  }

  if (!selectedDiagram) {
    return (
      <div className="flex-1 p-4 md:p-6">
        <div className="flex-1 space-y-6 mx-auto">
          <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
            <div>
              <h1 className="text-3xl font-medium tracking-tight">Data Flow Diagrams</h1>
              <p className="text-muted-foreground mt-1">
                <Package className="inline-block mr-2 h-4 w-4 text-muted-foreground" />
                {selectedProductData?.name}
              </p>
            </div>
            <div className="flex items-center gap-3">
              <Select value={selectedProduct.toString()} onValueChange={(val) => navigate(`/diagrams?product=${val}`)}>
                <SelectTrigger className="w-full sm:w-48">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {products.map((product) => (
                    <SelectItem key={product.id} value={product.id.toString()}>
                      {product.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {canWrite && (
                <Button onClick={openCreateWizard}>
                  <Plus className="mr-2 h-4 w-4" />
                  New Diagram
                </Button>
              )}
            </div>
          </div>

          {diagrams.length === 0 ? (
            <Card>
              <CardContent className="flex flex-col items-center justify-center p-12">
                <Grid3x3 className="h-12 w-12 text-muted-foreground mb-4" />
                <p className="text-lg font-medium mb-2">No diagrams yet</p>
                <p className="text-sm text-muted-foreground mb-6">
                  {canWrite ? 'Create your first diagram to start threat modeling' : 'No diagrams available for this product'}
                </p>
                {canWrite && (
                  <Button onClick={openCreateWizard}>
                    <Plus className="mr-2 h-4 w-4" />
                    Create Diagram
                  </Button>
                )}
              </CardContent>
            </Card>
          ) : (
            <div className="grid gap-4 sm:grid-cols-1 md:grid-cols-2 lg:grid-cols-3">
              {diagrams.map((diagram) => (
                <Card
                  key={diagram.id}
                  className="cursor-pointer hover:shadow-lg transition-shadow group"
                >
                  <CardContent className="p-6">
                    <div className="flex items-start justify-between">
                      <div
                        className="flex items-center gap-3 flex-1"
                        onClick={() => navigate(`/diagrams?product=${selectedProduct}&diagram=${diagram.id}`)}
                      >
                        <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10">
                          <Grid3x3 className="h-5 w-5 text-primary" />
                        </div>
                        <div>
                          <h3 className="font-semibold">{diagram.name}</h3>
                          <p className="text-sm text-muted-foreground">
                            {diagram.diagram_data?.nodes?.length || 0} elements
                          </p>
                        </div>
                      </div>
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          )}
        </div>
      </div>
    );
  }

  return (
    <div ref={containerRef} className={`h-full flex flex-col ${isFullscreen ? 'bg-background' : 'bg-muted/30'}`}>
      {/* ── Header ── */}
      <div className="h-14 border-b bg-background flex items-center justify-between px-3 z-20 shadow-sm relative sticky top-0">
        {/* Left: Breadcrumb */}
        <div className="flex items-center gap-0.5 min-w-0">
          <TooltipProvider>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button variant="ghost" size="icon" onClick={() => navigate('/')} className="h-8 w-8 shrink-0 hover:bg-muted">
                  <Home className="h-4 w-4 text-muted-foreground" />
                </Button>
              </TooltipTrigger>
              <TooltipContent>Home</TooltipContent>
            </Tooltip>
          </TooltipProvider>

          <ChevronRight className="h-3.5 w-3.5 text-muted-foreground/50 shrink-0" />

          <button
            onClick={() => navigate('/products')}
            className="text-sm text-muted-foreground hover:text-foreground transition-colors px-1.5 py-1 rounded-md hover:bg-muted shrink-0"
          >
            Products
          </button>

          <ChevronRight className="h-3.5 w-3.5 text-muted-foreground/50 shrink-0" />

          <button
            onClick={() => navigate(`/diagrams?product=${selectedProduct}`)}
            className="text-sm text-muted-foreground hover:text-foreground transition-colors px-1.5 py-1 rounded-md hover:bg-muted max-w-[140px] truncate shrink-0"
            title={selectedProductData?.name}
          >
            {selectedProductData?.name}
          </button>

          <ChevronRight className="h-3.5 w-3.5 text-muted-foreground/50 shrink-0" />

          <Input
            value={diagramName}
            onChange={(e) => setDiagramName(e.target.value)}
            className="h-8 border-none bg-transparent hover:bg-muted focus-visible:bg-muted transition-all duration-200 w-[90px] hover:w-[200px] focus:w-[200px] font-semibold text-sm focus-visible:ring-0 px-2 shrink-0"
            placeholder="Diagram name"
          />
        </div>

        {/* Right: Model selector + toolbar + save */}
        <div className="flex items-center gap-1.5 shrink-0">
          <div className="shrink-0">
            <ModelSelector
              diagramId={selectedDiagram}
              selectedModelId={activeModelId}
              onModelChange={(modelId, model) => {
                setActiveModelId(modelId);
                setActiveModel(model);
              }}
              externalCreateOpen={isCreatingModel}
              onExternalCreateClose={() => setIsCreatingModel(false)}
              externalEditOpen={isEditingModel}
              onExternalEditClose={() => setIsEditingModel(false)}
              externalDeleteOpen={isDeletingModel}
              onExternalDeleteClose={() => setIsDeletingModel(false)}
            />
          </div>

          {canWrite && (
            <TooltipProvider>
              <div className="h-8 w-px bg-border/40 mx-0.5 shrink-0" />

              <div className="flex items-center bg-muted/40 rounded-lg p-0.5 gap-0.5">
                {/* Model actions */}
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button variant="ghost" size="icon" className="h-8 w-8 text-primary hover:bg-primary/10"
                      onClick={() => setIsCreatingModel(true)}>
                      <Plus className="h-4 w-4" />
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent>New Model</TooltipContent>
                </Tooltip>

                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button variant="ghost" size="icon" className="h-8 w-8 text-muted-foreground hover:text-foreground"
                      onClick={() => setIsEditingModel(true)} disabled={!activeModelId}>
                      <Pencil className="h-4 w-4" />
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent>Edit Model</TooltipContent>
                </Tooltip>

                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button variant="ghost" size="icon" className="h-8 w-8 text-destructive/60 hover:text-destructive hover:bg-destructive/10"
                      onClick={() => setIsDeletingModel(true)} disabled={!activeModelId}>
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent>Delete Model</TooltipContent>
                </Tooltip>

                <div className="h-4 w-px bg-border/60 mx-0.5" />

                {/* Diagram actions */}
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button variant={showVersionComment ? 'secondary' : 'ghost'} size="icon" className="h-8 w-8"
                      onClick={() => setShowVersionComment(!showVersionComment)}>
                      <MessageSquare className="h-4 w-4" />
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent>Revision Note</TooltipContent>
                </Tooltip>

                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button variant="ghost" size="icon" className="h-8 w-8" onClick={handleExportJson}>
                      <Download className="h-4 w-4" />
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent>Download (JSON)</TooltipContent>
                </Tooltip>

                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button variant="ghost" size="icon" className="h-8 w-8" onClick={() => setVersionHistoryOpen(true)}>
                      <History className="h-4 w-4" />
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent>Version History</TooltipContent>
                </Tooltip>

                <div className="h-4 w-px bg-border/60 mx-0.5" />

                {/* AI + View */}
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button variant={aiChatOpen ? 'secondary' : 'ghost'} size="icon"
                      className="h-8 w-8 text-primary hover:text-primary hover:bg-primary/10"
                      onClick={() => setAiChatOpen(!aiChatOpen)}>
                      <Sparkles className="h-4 w-4" />
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent>AI Threat Analysis</TooltipContent>
                </Tooltip>

                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button variant="ghost" size="icon" className="h-8 w-8" onClick={() => fitView({ duration: 800 })}>
                      <Grid3x3 className="h-4 w-4" />
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent>Fit View</TooltipContent>
                </Tooltip>

                {/* Import Draw.io — shows choice when diagram is open */}
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button variant="ghost" size="icon" className="h-8 w-8"
                      onClick={() => {
                        if (selectedDiagram) {
                          setShowImportChoice(true);
                        } else {
                          setImportMode('new');
                          setImportDialogOpen(true);
                        }
                      }}>
                      <Upload className="h-4 w-4" />
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent>Import Draw.io</TooltipContent>
                </Tooltip>

                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button variant="ghost" size="icon" className="h-8 w-8" onClick={toggleFullscreen}>
                      {isFullscreen ? <Minimize className="h-4 w-4" /> : <Maximize className="h-4 w-4" />}
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent>{isFullscreen ? 'Exit Full Screen' : 'Full Screen'}</TooltipContent>
                </Tooltip>
              </div>

              <div className="h-8 w-px bg-border/40 mx-0.5 shrink-0" />

              <Button
                onClick={handleSaveDiagram}
                disabled={saving}
                size="sm"
                className="h-9 px-4 font-semibold shadow-sm bg-primary hover:bg-primary/90 transition-all active:scale-95"
              >
                <Save className="mr-1.5 h-4 w-4" />
                {saving ? 'Saving…' : 'Save'}
              </Button>
            </TooltipProvider>
          )}
        </div>
      </div>

      {/* Floating Note Component */}
      {showVersionComment && (
        <div className="absolute top-16 right-4 z-50 w-80 shadow-2xl animate-in slide-in-from-top-4 duration-200">
          <Card className="border-primary/20 bg-background/95 backdrop-blur">
            <CardContent className="p-3">
              <div className="flex items-center justify-between mb-2">
                <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Version Note</span>
                <Button variant="ghost" size="icon" className="h-5 w-5" aria-label="Close version note" onClick={() => setShowVersionComment(false)}>
                  <Plus className="h-3 w-3 rotate-45" />
                </Button>
              </div>
              <Textarea
                value={versionComment}
                onChange={(e) => setVersionComment(e.target.value)}
                placeholder="What changed in this version?"
                className="text-sm min-h-[100px] resize-none focus-visible:ring-1"
                autoFocus
              />
            </CardContent>
          </Card>
        </div>
      )}
      {/* Canvas */}
      <div className="flex-1 relative" style={{ minHeight: '400px' }}>
        <ReactFlow
          nodes={nodesWithCounts}
          edges={edges}
          nodeTypes={nodeTypes}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={onConnect}
          onNodeClick={handleNodeClick}
          onEdgeClick={handleEdgeClick}
          onNodeDrag={onNodeDrag}
          onNodeDragStop={onNodeDragStop}
          elevateNodesOnSelect={false}
          fitView
          className="bg-muted/20"
          proOptions={{ hideAttribution: true }}
        >
          {/* Floating Action Menu for Node Creation */}
          <Panel position="top-left" className="m-4">
            <Card className="shadow-2xl border bg-background/95 backdrop-blur-md w-52 max-h-[calc(100vh-8rem)] overflow-y-auto">
              <div className="p-2 space-y-1">
                <div className="px-2 py-1.5 text-[10px] font-bold text-muted-foreground uppercase tracking-wider">
                  Diagram Tools
                </div>
                <Button
                  variant="ghost"
                  onClick={() => addNode('process')}
                  className="w-full justify-start gap-3 h-10 px-3 hover:bg-primary/10 hover:text-primary transition-all rounded-lg group"
                >
                  <Cpu className="h-5 w-5 text-primary group-hover:scale-110 transition-transform" />
                  <span className="text-sm font-medium">Process</span>
                </Button>
                <Button
                  variant="ghost"
                  onClick={() => addNode('datastore')}
                  className="w-full justify-start gap-3 h-10 px-3 transition-all rounded-lg group"
                  onMouseEnter={e => (e.currentTarget.style.backgroundColor = 'color-mix(in srgb, var(--element-datastore) 12%, transparent)')}
                  onMouseLeave={e => (e.currentTarget.style.backgroundColor = '')}
                >
                  <Database className="h-5 w-5 group-hover:scale-110 transition-transform" style={{ color: 'var(--element-datastore)' }} />
                  <span className="text-sm font-medium">Data Store</span>
                </Button>
                <Button
                  variant="ghost"
                  onClick={() => addNode('external')}
                  className="w-full justify-start gap-3 h-10 px-3 transition-all rounded-lg group"
                  onMouseEnter={e => (e.currentTarget.style.backgroundColor = 'color-mix(in srgb, var(--element-external) 12%, transparent)')}
                  onMouseLeave={e => (e.currentTarget.style.backgroundColor = '')}
                >
                  <Users className="h-5 w-5 group-hover:scale-110 transition-transform" style={{ color: 'var(--element-external)' }} />
                  <span className="text-sm font-medium">External Entity</span>
                </Button>
                <Button
                  variant="ghost"
                  onClick={() => addNode('boundary')}
                  className="w-full justify-start gap-3 h-10 px-3 transition-all rounded-lg group"
                  onMouseEnter={e => (e.currentTarget.style.backgroundColor = 'color-mix(in srgb, var(--element-boundary) 15%, transparent)')}
                  onMouseLeave={e => (e.currentTarget.style.backgroundColor = '')}
                >
                  <BoxIcon className="h-5 w-5 group-hover:scale-110 transition-transform" style={{ color: 'var(--element-boundary)' }} />
                  <span className="text-sm font-medium">Trust Boundary</span>
                </Button>
              </div>
            </Card>
          </Panel>

          <Controls className="bg-background border shadow-xl rounded-lg overflow-hidden" />
          <MiniMap
            className="bg-background border shadow-xl rounded-xl"
            nodeColor={(node) => {
              const type = node.data.type as string;
              if (type === 'process') return 'var(--primary)';
              if (type === 'datastore') return 'var(--element-datastore)';
              if (type === 'external') return 'var(--element-external)';
              return 'var(--element-boundary)';
            }}
            maskColor="rgba(0, 0, 0, 0.05)"
          />
          <Background variant={BackgroundVariant.Dots} gap={16} size={1} className="bg-muted/10" />

        </ReactFlow>
      </div>

      {/* Element Properties Sheet */}
      <ElementPropertiesSheet
        open={sheetOpen}
        onOpenChange={(v) => {
          setSheetOpen(v);
          if (!v && selectedDiagram) loadElementCounts(selectedDiagram, activeModelId);
        }}
        selectedElement={selectedElement}
        diagramId={selectedDiagram}
        activeModelId={activeModelId}
        activeModelFrameworkId={activeModel?.framework_id || null}
        onDescriptionChange={(description) => {
          if (!selectedElement || selectedElement.type !== 'node') return;
          setNodes((nds) =>
            nds.map((node) =>
              node.id === selectedElement.id
                ? { ...node, data: { ...node.data, description } }
                : node
            )
          );
          setSelectedElement({ ...selectedElement, description });
        }}
        onRename={(name) => {
          if (!selectedElement) return;
          if (selectedElement.type === 'node') {
            setNodes((nds) =>
              nds.map((node) =>
                node.id === selectedElement.id
                  ? { ...node, data: { ...node.data, label: name } }
                  : node
              )
            );
          } else if (selectedElement.type === 'edge') {
            setEdges((eds) =>
              eds.map((edge) =>
                edge.id === selectedElement.id
                  ? { ...edge, label: name }
                  : edge
              )
            );
          }
          setSelectedElement({ ...selectedElement, label: name });
        }}
        onChangeType={(newType) => {
          if (!selectedElement || selectedElement.type !== 'node') return;
          // Fixed rendered sizes for non-boundary types (matches DiagramNode shapes).
          const FIXED_SIZE: Record<string, { w: number; h: number }> = {
            process:   { w: 96,  h: 96  },
            datastore: { w: 140, h: 40  },
            external:  { w: 120, h: 44  },
          };
          setNodes((nds) =>
            nds.map((node) => {
              if (node.id !== selectedElement.id) return node;
              const oldType = node.data.type as string;
              const fixed = FIXED_SIZE[newType];
              // boundary → fixed-size: recompute position from centre of old boundary box
              // so the element doesn't jump to a corner and handles land on the new shape.
              let position = node.position;
              if (oldType === 'boundary' && fixed && node.width && node.height) {
                const cx = node.position.x + node.width / 2;
                const cy = node.position.y + node.height / 2;
                position = { x: cx - fixed.w / 2, y: cy - fixed.h / 2 };
              }
              return {
                ...node,
                position,
                zIndex: newType === 'boundary' ? -1 : 10,
                // Clear explicit dimensions for fixed-size types so ReactFlow
                // measures the rendered element and positions handles correctly.
                width:  newType === 'boundary' ? (node.width  ?? 300) : undefined,
                height: newType === 'boundary' ? (node.height ?? 200) : undefined,
                data: { ...node.data, type: newType },
              };
            })
          );
          setSelectedElement({ ...selectedElement, nodeType: newType });
        }}
        onDelete={() => setShowDeleteConfirm(true)}
        portalContainer={containerRef.current}
      />

      {/* Delete Element Confirmation Dialog */}
      <AlertDialog open={showDeleteConfirm} onOpenChange={setShowDeleteConfirm}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete Element</AlertDialogTitle>
            <AlertDialogDescription>
              Are you sure you want to delete "{selectedElement?.label}"? This action cannot be undone and will also remove all associated threats and mitigations.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                handleDeleteElement();
                setShowDeleteConfirm(false);
              }}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Delete Diagram Confirmation Dialog */}
      <AlertDialog open={!!diagramToDelete} onOpenChange={() => setDiagramToDelete(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete Diagram</AlertDialogTitle>
            <AlertDialogDescription>
              Are you sure you want to delete "{diagramToDelete?.name}"? This action cannot be undone and will delete all elements, threats, and mitigations in this diagram.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleDeleteDiagram}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Version History Sheet */}
      <DiagramVersionHistory
        open={versionHistoryOpen}
        onOpenChange={setVersionHistoryOpen}
        diagramId={selectedDiagram}
        currentVersion={currentVersion}
        onRestore={handleVersionRestore}
        onCompare={handleVersionCompare}
      />

      {/* Version Comparison Dialog */}
      {compareVersions && (
        <DiagramVersionComparison
          open={!!compareVersions}
          onOpenChange={(open) => !open && setCompareVersions(null)}
          diagramId={selectedDiagram}
          fromVersion={compareVersions.from}
          toVersion={compareVersions.to}
        />
      )}

      {/* ── Create Diagram Wizard ─────────────────────────────────────────── */}
      <Dialog
        open={showCreateWizard}
        onOpenChange={(v) => { if (!v) { setShowCreateWizard(false); setWizardStep('choose'); } }}
      >
        <DialogContent className="sm:max-w-lg">
          {wizardStep === 'choose' && (
            <>
              <DialogHeader>
                <DialogTitle>New Diagram</DialogTitle>
                <DialogDescription>
                  Start with a blank canvas or import an existing Draw.io file.
                </DialogDescription>
              </DialogHeader>

              <div className="grid grid-cols-2 gap-3 py-2">
                <button
                  onClick={() => setWizardStep('blank')}
                  className="flex flex-col items-center gap-3 rounded-xl border-2 border-border/60 bg-muted/30 p-6 text-left hover:border-primary/50 hover:bg-primary/5 transition-all duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40"
                >
                  <div className="flex h-12 w-12 items-center justify-center rounded-full bg-primary/10">
                    <Grid3x3 className="h-6 w-6 text-primary" />
                  </div>
                  <div>
                    <p className="font-semibold text-sm text-center">Blank Canvas</p>
                    <p className="text-xs text-muted-foreground text-center mt-0.5">Start from scratch</p>
                  </div>
                </button>

                <button
                  onClick={() => {
                    setImportMode('new');
                    setShowCreateWizard(false);
                    setImportDialogOpen(true);
                  }}
                  className="flex flex-col items-center gap-3 rounded-xl border-2 border-border/60 bg-muted/30 p-6 text-left hover:border-primary/50 hover:bg-primary/5 transition-all duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40"
                >
                  <div className="flex h-12 w-12 items-center justify-center rounded-full bg-primary/10">
                    <Upload className="h-6 w-6 text-primary" />
                  </div>
                  <div>
                    <p className="font-semibold text-sm text-center">Import Draw.io</p>
                    <p className="text-xs text-muted-foreground text-center mt-0.5">.drawio or .xml file</p>
                  </div>
                </button>
              </div>
            </>
          )}

          {wizardStep === 'blank' && (
            <>
              <DialogHeader>
                <DialogTitle>Name your diagram</DialogTitle>
                <DialogDescription>
                  Give this diagram a name — you can always change it later.
                </DialogDescription>
              </DialogHeader>

              <div className="space-y-2 py-2">
                <Label htmlFor="new-diagram-name">Diagram name</Label>
                <Input
                  id="new-diagram-name"
                  value={newDiagramName}
                  onChange={(e) => setNewDiagramName(e.target.value)}
                  placeholder="e.g. Payment Service DFD"
                  autoFocus
                  onKeyDown={(e) => e.key === 'Enter' && handleCreateBlankDiagram()}
                />
              </div>

              <DialogFooter className="gap-2">
                <button
                  className="text-sm text-muted-foreground hover:text-foreground underline-offset-4 hover:underline mr-auto"
                  onClick={() => setWizardStep('choose')}
                >
                  Back
                </button>
                <Button variant="outline" onClick={() => setShowCreateWizard(false)}>Cancel</Button>
                <Button
                  onClick={handleCreateBlankDiagram}
                  disabled={!newDiagramName.trim() || creatingBlank}
                >
                  {creatingBlank ? 'Creating…' : 'Create Diagram'}
                </Button>
              </DialogFooter>
            </>
          )}
        </DialogContent>
      </Dialog>

      {/* Import choice dialog — new diagram vs replace current */}
      <Dialog open={showImportChoice} onOpenChange={setShowImportChoice}>
        <DialogContent className="sm:max-w-sm">
          <DialogHeader>
            <DialogTitle>Import Draw.io</DialogTitle>
            <DialogDescription>
              How would you like to import the file?
            </DialogDescription>
          </DialogHeader>
          <div className="grid grid-cols-2 gap-3 py-2">
            <button
              type="button"
              onClick={() => { setImportMode('new'); setShowImportChoice(false); setImportDialogOpen(true); }}
              className="flex flex-col items-center gap-3 rounded-xl border-2 border-border/60 bg-muted/30 p-5 hover:border-primary/50 hover:bg-primary/5 transition-all duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40"
            >
              <div className="flex h-11 w-11 items-center justify-center rounded-full bg-primary/10">
                <Plus className="h-5 w-5 text-primary" />
              </div>
              <div>
                <p className="font-semibold text-sm text-center">New Diagram</p>
                <p className="text-xs text-muted-foreground text-center mt-0.5">Create a separate diagram</p>
              </div>
            </button>
            <button
              type="button"
              onClick={() => { setImportMode('replace'); setShowImportChoice(false); setImportDialogOpen(true); }}
              className="flex flex-col items-center gap-3 rounded-xl border-2 border-border/60 bg-muted/30 p-5 hover:border-primary/50 hover:bg-primary/5 transition-all duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40"
            >
              <div className="flex h-11 w-11 items-center justify-center rounded-full bg-orange-500/10">
                <Upload className="h-5 w-5 text-orange-500" />
              </div>
              <div>
                <p className="font-semibold text-sm text-center">Replace Current</p>
                <p className="text-xs text-muted-foreground text-center mt-0.5">Overwrite this diagram</p>
              </div>
            </button>
          </div>
        </DialogContent>
      </Dialog>

      {/* Controlled ImportDrawioButton */}
      {selectedProduct && (
        <ImportDrawioButton
          productId={selectedProduct}
          onImportSuccess={handleImportSuccess}
          open={importDialogOpen}
          onOpenChange={setImportDialogOpen}
          targetDiagramId={importMode === 'replace' && selectedDiagram ? selectedDiagram : undefined}
          initialName={importMode === 'replace' ? diagramName : undefined}
        />
      )}

      {/* AI Chat Sheet */}
      <AIChatSheet
        open={aiChatOpen}
        onOpenChange={setAiChatOpen}
        diagramId={selectedDiagram}
        activeModelId={activeModelId}
        frameworkId={activeModel?.framework_id ?? null}
        portalContainer={containerRef.current}
        onModelCreated={(modelId, model) => {
          setActiveModelId(modelId);
          setActiveModel(model);
        }}
        onProposalApproved={() => {
          if (selectedDiagram) loadElementCounts(selectedDiagram, activeModelId);
        }}
      />
    </div>
  );
}

// Wrapper to provide ReactFlow context
export default function Diagrams() {
  return (
    <ReactFlowProvider>
      <DiagramsContent />
    </ReactFlowProvider>
  );
}
