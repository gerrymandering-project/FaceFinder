# -*- coding: utf-8 -*-
"""
Created on Sat Oct 13 19:39:52 2018
@author: Temporary
"""

#This will take a graph that (I know is) planar along with position data on the nodes, and construct face data.
import requests
from gerrychain import Graph, Partition
from networkx.readwrite import json_graph
import json
import networkx as nx
import numpy as np
import matplotlib.pyplot as plt
from gerrychain.updaters import Tally, cut_edges
import math
import random


def compute_rotation_system(graph):
    # Graph nodes must have "pos" and is promised that the embedding is a straight line embedding
    # The graph will be returned in a way that every node has a dictionary that gives you the next edge clockwise around that node
    # The rotation system is  clockwise (0,2) -> (1,1) -> (0,0) around (0,1)
    for v in graph.nodes():
        graph.nodes[v]["pos"] = np.array(graph.nodes[v]["pos"])

    for v in graph.nodes():
        locations = []
        neighbor_list = list(graph.neighbors(v))
        for w in neighbor_list:
            locations.append(graph.nodes[w]["pos"] - graph.nodes[v]["pos"])
        angles = [float(np.arctan2(x[0], x[1])) for x in locations]
        neighbor_list.sort(key=dict(zip(neighbor_list, angles)).get)
        # sorted_neighbors = [x for _,x in sorted(zip(angles, neighbor_list))]
        rotation_system = {}
        for i in range(len(neighbor_list)):
            rotation_system[neighbor_list[i]] = neighbor_list[(i + 1) % len(neighbor_list)]
        graph.nodes[v]["rotation"] = rotation_system
    return graph


def transform(x):
    # takes x from [-pi, pi] and puts it in [0,pi]
    if x >= 0:
        return x
    if x < 0:
        return 2 * np.pi + x


def is_clockwise(graph, face, average):
    # given a face (with respect to the rotation system computed), determine if it belongs to a the orientation assigned to bounded faces
    angles = [transform(float(np.arctan2(graph.nodes[x]["pos"][0] - average[0], graph.nodes[x]["pos"][1] - average[1])))
              for x in face]
    first = min(angles)
    rotated = [x - first for x in angles]
    next_smallest = min([x for x in rotated if x != 0])
    ind = rotated.index(0)
    if rotated[(ind + 1) % len(rotated)] == next_smallest:
        return False
    else:
        return True


def cycle_around_face(graph, e):
    # Faces are being stored as the list of vertices
    face = list([e[0], e[1]])
    # starts off with the two vertices of the edge e
    last_point = e[1]
    current_point = graph.nodes[e[1]]["rotation"][e[0]]
    next_point = current_point
    while next_point != e[0]:
        face.append(current_point)
        next_point = graph.nodes[current_point]["rotation"][last_point]
        last_point = current_point
        current_point = next_point
    return face


def compute_face_data(graph):
    # graph must already have a rotation_system
    faces = []
    # faces will stored as sets of vertices

    for e in graph.edges():
        # need to make sure you get both possible directions for each edge..

        face = cycle_around_face(graph, e)
        faces.append(tuple(face))
        # has to get passed to a tuple because networkx wants the names of vertices to be frozen
        face = cycle_around_face(graph, [e[1], e[0]])
        # also cycle in the other direction
        faces.append(tuple(face))
    # detect the unbounded face based on orientation
    bounded_faces = []
    unbounded_face = 0
    for face in faces:
        run_sum = np.array([0, 0]).astype('float64')
        for x in face:
            run_sum += np.array(graph.nodes[x]["pos"]).astype('float64')
        average = run_sum / len(face)
        # associate each face to the average of the vertices
        if is_clockwise(graph, face, average):
            # figures out whether a face is bounded or not based on clockwise orientation
            bounded_faces.append(face)
        else:
            unbounded_face = face
    # print(unbounded_face)
    bounded_faces_list = [frozenset(face) for face in bounded_faces]
    graph.graph["bounded_faces"] = set(bounded_faces_list)
    # print(bounded_faces_list)
    all_faces = bounded_faces_list + [frozenset(unbounded_face)]

    graph.graph["all_faces"] = set(all_faces)

    return graph


def compute_all_faces(graph):
    # graph must already have a rotation_system
    faces = []
    # faces will stored as sets of vertices

    for e in graph.edges():
        # need to make sure you get both possible directions for each edge..

        face = cycle_around_face(graph, e)
        faces.append(tuple(face))
        face = cycle_around_face(graph, [e[1], e[0]])
        faces.append(tuple(face))

    # This overcounts, have to delete cyclic repeats now:

    sorted_faces = list(set([tuple(canonical_order(graph, x)) for x in faces]))
    cleaned_faces = [tuple([y for y in F]) for F in sorted_faces]
    graph.graph["faces"] = cleaned_faces
    return graph


def canonical_order(graph, face):
    '''
    Outputs the coordinates of the nodes of the face in a canonical order
    in particular, the first one is the lex-min.

    You need to use the graph structure to make this work
    '''

    lex_sorted_nodes = sorted(face)
    first_node = lex_sorted_nodes[0]
    cycle_sorted_nodes = [first_node]
    local_cycle = nx.subgraph(graph, face)

    # Compute the second node locally based on angle orientation

    v = first_node
    locations = []
    neighbor_list = list(local_cycle.neighbors(v))
    for w in neighbor_list:
        locations.append(graph.nodes[w]["pos"] - graph.nodes[v]["pos"])
    angles = [float(np.arctan2(x[1], x[0])) for x in locations]
    neighbor_list.sort(key=dict(zip(neighbor_list, angles)).get)

    second_node = neighbor_list[0]
    cycle_sorted_nodes.append(second_node)
    ##Now compute a canonical ordering of local_cycle, clockwise, starting
    ##from first_node

    while len(cycle_sorted_nodes) < len(lex_sorted_nodes):
        v = cycle_sorted_nodes[-1]
        neighbor_list = list(local_cycle.neighbors(v))
        neighbor_list.remove(cycle_sorted_nodes[-2])
        cycle_sorted_nodes.append(neighbor_list[0])

    return cycle_sorted_nodes


def delete_copies_up_to_permutation(array):
    '''
    Given an array of tuples, return an array consisting of one representative
    for each element in the orbit of the reordering action.
    '''

    cleaned_array = list(set([tuple(canonical_order(x)) for x in array]))

    return cleaned_array


def face_refine(graph):
    # graph must already have the face data computed
    # this adds a vetex in the middle of each face, and connects that vertex to the edges of that face...

    for face in graph.graph["faces"]:
        graph.add_node(face)
        location = np.array([0, 0]).astype("float64")
        for v in face:
            graph.add_edge(face, v)
            location += graph.nodes[v]["pos"].astype("float64")
        graph.nodes[face]["pos"] = location / len(face)
    return graph


def edge_refine(graph):
    edge_list = list(graph.edges())
    for e in edge_list:
        graph.remove_edge(e[0], e[1])
        graph.add_node(str(e))
        location = np.array([0, 0]).astype("float64")
        for v in e:
            graph.add_edge(str(e), v)
            location += graph.nodes[v]["pos"].astype("float64")
        graph.nodes[str(e)]["pos"] = location / 2
    return graph


def refine(graph):
    graph = compute_rotation_system(graph)
    graph = compute_face_data(graph)
    graph = face_refine(graph)
    return graph


def depth_k_refine(graph, k):
    graph.name = graph.name + str("refined_depth") + str(k)
    for i in range(k):
        graph = refine(graph)
    return graph


def depth_k_barycentric(graph, k):
    graph.name = graph.name + str("refined_depth") + str(k)
    for i in range(k):
        graph = barycentric_subdivision(graph)
    return graph


def barycentric_subdivision(graph):
    # graph must already have the face data computed
    # this adds a vetex in the middle of each face, and connects that vertex to the edges of that face...
    graph = edge_refine(graph)
    graph = refine(graph)
    return graph


def restricted_planar_dual(graph):
    return planar_dual(graph, True)


def planar_dual(graph, restricted=False):
    # computes dual without unbounded face
    graph = compute_rotation_system(graph)
    graph = compute_face_data(graph)
    if restricted == True:
        faces = graph.graph["bounded_faces"]
    else:
        faces = graph.graph["all_faces"]
    dual_graph = nx.Graph()
    for face in faces:
        dual_graph.add_node(face)
        location = np.array([0, 0]).astype("float64")
        for v in face:
            location += graph.nodes[v]["pos"].astype("float64")
        dual_graph.nodes[face]["pos"] = location / len(face)
    ##handle edges
    for e in graph.edges():
        for face1 in faces:
            for face2 in faces:
                if face1 != face2:
                    if (e[0] in face1) and (e[1] in face1) and (e[0] in face2) and (e[1] in face2):
                        dual_graph.add_edge(face1, face2)
                        dual_graph.edges[(face1, face2)]["original_name"] = e
    return dual_graph

##

def draw_with_location(graph):
    '''
    draws graph with 'pos' as the xy coordinate of each nodes
    initialized by something like graph.nodes[x]["pos"] = np.array([x[0], x[1]])
    '''
#    for x in graph.nodes():
#        graph.nodes[x]["pos"] = [graph.nodes[x]["X"], graph.nodes[x]["Y"]]
    plt.figure()
    nx.draw(graph, pos=nx.get_node_attributes(graph, 'pos'), node_size = 20, width = .5, cmap=plt.get_cmap('jet'))
    plt.show()
##

def bnodes_p(partition):
    return [x for x in graph.nodes() if graph.node[x]["boundary_node"] == 1]

def new_base(partition):
    base = 1
    return base


def step_num(partition):
    parent = partition.parent

    if not parent:
        return 0

    return parent["step_num"] + 1


# bnodes = [x for x in graph.nodes() if graph.node[x]["boundary_node"] == 1]


def bnodes_p(partition):
    return [x for x in graph.nodes() if graph.node[x]["boundary_node"] == 1]

def b_nodes_bi(partition):
    return {x[0] for x in partition["cut_edges"]}.union({x[1] for x in partition["cut_edges"]})

def geom_wait(partition):
    return int(np.random.geometric(
        len(list(partition["b_nodes"])) / (len(partition.graph.nodes) ** (len(partition.parts)) - 1), 1)) - 1


# TODO: build partition using spanning trees to find edges
def buildPartition(graph, mean):
    # horizontal = []
    assignment = {}
    for x in graph.node():
        if graph.node[x]['C_X'] < mean:
            assignment[x] = -1
        else:
            assignment[x] = 1

    updaters = {'population': Tally('population'),
                "boundary": bnodes_p,
                'cut_edges': cut_edges,
                'step_num': step_num,
                'b_nodes': b_nodes_bi,
                'base': new_base,
                'geom': geom_wait,
                }

    grid_partition = Partition(graph, assignment=assignment, updaters=updaters)
    return grid_partition


def compute_cross_edge(graph, partition):
    cross_list = []
    for n in graph.edges:
        if Partition.crosses_parts(partition, n):
            cross_list.append(n)
    return cross_list # cut edges of partiitons


def viz(graph, edge_set, partition):
    values = [1 - int(x in edge_set) for x in graph.edges()]
    # node_labels = {x : x for x in graph.nodes()}
    distance_dictionary = {}
    for x in graph.nodes():
        distance_dictionary[x] = graph.node[x]['distance']
    color_dictionary = {}
    for x in graph.nodes():
        if x in partition.parts[-1]:
            color_dictionary[x] = 1
        else:
            color_dictionary[x] = 2
    node_values = [color_dictionary[x] for x in graph.nodes()]
    plt.figure()
    nx.draw(graph, pos=nx.get_node_attributes(graph, 'pos'), node_color = node_values, edge_color = values, labels = distance_dictionary,  width = 4, node_size= 0, font_size = 7)
    plt.show()
    #f.savefig(str(int(time.time())) + ".png")

# # TODO: pick out every node from edges
# def edge_list_to_node_list(list_of_edges):
#
#     return 0

def distance_from_partition(graph, boundary_edges):
#general Idea:
#Goal: Given any face of the original graph, want to calculate its distance to the boundary of the partition.
#Method: Treat that face as a vertex v of the dual graph D, and then (using above) treat the boundary of the partition of a set of vertices S of the dual graph.
# Then calculate distance from v to S in D, using:
#d = infinity
#For each s in S:
 #    d = min ( distance_in_D(v,s), d)
    for node in graph.nodes():
        dist = math.inf
        for bound in boundary_edges:
            if node == bound[0] or node == bound[1]:
                dist = 0
            else:
                dist = min(dist, len(nx.shortest_path(graph, source = node, target = bound[0])) - 1)
                dist = min(dist, len(nx.shortest_path(graph, source = node, target = bound[1])) - 1)
        graph.node[node]["distance"] = dist
    return graph


# # TODO: find distance by recursive slack
# def distance_in_D(dual, face, s):
#     path = nx.shortest_path(dual, face, s)
#     distance = len(path)
#     return distance
#
#
# def cal_distance(dual, dual_list, face):
#     distance = math.inf
#     for s in dual_list:
#         distance = min(distance, distance_in_D(dual, face, s))
#     return distance


# link = input("Put graph link: ")
# link = "https://people.csail.mit.edu/ddeford//COUNTY/COUNTY_23.json"
link = "https://people.csail.mit.edu/ddeford//COUNTY/COUNTY_13.json"
r = requests.get(link)
data = json.loads(r.content)
g = json_graph.adjacency_graph(data)
graph = Graph(g)
graph.issue_warnings()

horizontal = []
node_degree_1 = []
# for x in graph.nodes():
#     graph.nodes[x]["pos"] = np.array(x[0], x[1])
for node in graph.nodes():
    graph.nodes[node]["pos"] = [graph.node[node]['C_X'], graph.node[node]['C_Y']]
    horizontal.append(graph.node[node]['C_X'])
    if graph.degree(node) == 1 or graph.degree(node) == 2:
        node_degree_1.append(node)

for i in node_degree_1:
    graph.remove_node(i)

mean = sum(horizontal) / len(horizontal)

# m= 5
# graph = nx.grid_graph([m,m])
# graph.name = "grid_size:" + str(m)
# for x in graph.nodes():
#
#     graph.nodes[x]["pos"] = np.array([x[0], x[1]])

###graph = depth_k_refine(graph,0)
##graph = depth_k_barycentric(graph, 4)
draw_with_location(graph)
#graph = compute_rotation_system(graph)
#This makes it so that the graph has the rotation system around each vertex

#graph = compute_face_data(graph)
##print(len(graph.graph["faces"]))
##
dual = planar_dual(graph, False)
draw_with_location(dual)
#Every node of the dual is a crozenset of the vertices of the face.

partition = buildPartition(graph, mean)
cross_edges_in_graph = compute_cross_edge(graph, partition)


dual_list = [] # dual edges cross primal edges

for edge in dual.edges:
    if dual.edges[edge]["original_name"] in cross_edges_in_graph:
        print(len(dual_list))

        #dual_list.append(dual.edges[edge]["original_name"])
        dual_list.append(edge)


used_edges = []
visual_edges = []
for edge in dual.edges:
    if dual.edges[edge]["original_name"] not in used_edges:
        used_edges.append(dual.edges[edge]["original_name"])
    else:
        print(edge, dual.edges[edge]["original_name"])
        visual_edges.append(dual.edges[edge]["original_name"])


# viz(graph, cross_edges_in_graph, partition)

distance_from_partition(graph, cross_edges_in_graph)
viz(graph, cross_edges_in_graph, partition)

# random_face = random.choice(list(dual.nodes()))
